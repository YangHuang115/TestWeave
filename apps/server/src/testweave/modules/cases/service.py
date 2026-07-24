import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    CaseModule,
    CaseNumberSequence,
    Project,
    TestCase,
    TestCaseEditSession,
    TestCaseMindmap,
    TestCaseModuleRelation,
    TestCaseRevision,
    TestCaseStep,
    TestTask,
    User,
)
from testweave.modules.test_tasks.service import TestTaskService


def utc_now() -> datetime:
    return datetime.now(UTC)


def _get_active_case_design_task(
    db: Session,
    project_id: str,
    task_id: str,
) -> TestTask:
    task = TestTaskService.get_task_by_id(db, project_id, task_id)
    if task.task_type != "CASE_DESIGN" or task.archived_at is not None:
        raise AppError(
            code="TEST_TASK_NOT_FOUND",
            message="测试任务不存在或无权限访问",
            status_code=404,
        )
    return task


class TestCaseService:
    @staticmethod
    def _get_project_case(db: Session, project_id: str, case_id: str) -> TestCase:
        proj_uuid = uuid.UUID(str(project_id))
        case_uuid = uuid.UUID(str(case_id))
        stmt = select(TestCase).where(
            TestCase.id == case_uuid,
            TestCase.project_id == proj_uuid,
            TestCase.deleted_at.is_(None),
        )
        case = db.scalar(stmt)
        if not case:
            raise AppError(code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404)
        return case

    @staticmethod
    def _get_open_project_session(
        db: Session,
        project_id: str,
        case_id: str,
        session_id: str,
    ) -> TestCaseEditSession:
        proj_uuid = uuid.UUID(str(project_id))
        case_uuid = uuid.UUID(str(case_id))
        sess_uuid = uuid.UUID(str(session_id))
        stmt = (
            select(TestCaseEditSession)
            .join(TestCase, TestCase.id == TestCaseEditSession.case_id)
            .where(
                TestCaseEditSession.id == sess_uuid,
                TestCaseEditSession.case_id == case_uuid,
                TestCaseEditSession.status == "OPEN",
                TestCase.project_id == proj_uuid,
                TestCase.deleted_at.is_(None),
            )
        )
        session = db.scalar(stmt)
        if not session:
            raise AppError(
                code="EDIT_SESSION_NOT_FOUND", message="活跃的编辑会话不存在", status_code=404
            )
        return session

    @staticmethod
    def generate_next_case_no(db: Session, project_id: str) -> str:
        """悲观锁并发安全生成下一个用例编号：TC-XXXXXX"""
        proj_uuid = uuid.UUID(str(project_id))
        stmt = (
            select(CaseNumberSequence)
            .where(CaseNumberSequence.project_id == proj_uuid)
            .with_for_update()
        )
        seq = db.scalar(stmt)
        if not seq:
            seq = CaseNumberSequence(project_id=proj_uuid, current_value=1)
            db.add(seq)
        else:
            seq.current_value += 1
        db.flush()
        return f"TC-{seq.current_value:06d}"

    @staticmethod
    def create_case(
        db: Session,
        project_id: str,
        title: str,
        precondition: str | None,
        priority: str,
        case_type: str,
        tags_json: list[str],
        test_data_note: str | None,
        note: str | None,
        steps: list[dict[str, Any]],
        source_task_id: str | None,
        actor_id: str,
        request_id: str,
        module_ids: list[str] | None = None,
    ) -> TestCase:
        """创建用例，并产生初始 Revision 1 历史版本"""
        proj_uuid = uuid.UUID(str(project_id))
        actor_uuid = uuid.UUID(str(actor_id))

        # 校验项目
        project = db.get(Project, proj_uuid)
        if not project:
            raise AppError(code="PROJECT_NOT_FOUND", message="关联项目不存在", status_code=404)

        # 校验创建人
        user = db.get(User, actor_uuid)
        if not user:
            raise AppError(code="USER_NOT_FOUND", message="创建人不存在", status_code=404)

        # 校验关联任务
        if source_task_id:
            _get_active_case_design_task(db, project_id, source_task_id)

        # 自动生成编号
        case_no = TestCaseService.generate_next_case_no(db, project_id)

        # 创建 TestCase 实例
        case = TestCase(
            project_id=proj_uuid,
            case_no=case_no,
            title=title.strip(),
            precondition=precondition,
            priority=priority,
            case_type=case_type,
            tags_json=tags_json,
            test_data_note=test_data_note,
            note=note,
            source_task_id=uuid.UUID(str(source_task_id)) if source_task_id else None,
            row_version=1,
            created_by=actor_uuid,
            updated_by=actor_uuid,
        )
        db.add(case)
        db.flush()

        # 写入步骤
        db_steps = []
        for index, s in enumerate(steps, start=1):
            step = TestCaseStep(
                case_id=case.id,
                step_order=index,
                action=s.get("action", "").strip(),
                expected_result=s.get("expected_result", "").strip(),
                note=s.get("note"),
            )
            db.add(step)
            db_steps.append(step)
        db.flush()

        # 写入模块关联
        if module_ids:
            for mid in module_ids:
                module_uuid = uuid.UUID(str(mid))
                module = db.get(CaseModule, module_uuid)
                if not module or module.project_id != proj_uuid:
                    raise AppError(
                        code="CASE_MODULE_NOT_FOUND",
                        message=f"用例模块不存在: {mid}",
                        status_code=404,
                    )
                relation = TestCaseModuleRelation(
                    case_id=case.id,
                    module_id=module_uuid,
                    created_by=actor_uuid,
                )
                db.add(relation)
            db.flush()

        # 打包初始修订快照
        snapshot = {
            "title": case.title,
            "precondition": case.precondition,
            "priority": case.priority,
            "case_type": case.case_type,
            "tags_json": case.tags_json,
            "test_data_note": case.test_data_note,
            "note": case.note,
            "steps": [
                {
                    "step_order": s.step_order,
                    "action": s.action,
                    "expected_result": s.expected_result,
                    "note": s.note,
                }
                for s in db_steps
            ],
        }
        serialized_snapshot = json.dumps(snapshot, sort_keys=True)
        snapshot_hash = hashlib.sha256(serialized_snapshot.encode("utf-8")).hexdigest()

        revision = TestCaseRevision(
            case_id=case.id,
            revision_no=1,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
            change_summary={"type": "CREATE", "note": "创建初始版本"},
            created_by=actor_uuid,
        )
        db.add(revision)
        db.flush()

        # 回填当前 revision ID
        case.current_revision_id = revision.id
        db.flush()

        return case

    @staticmethod
    def start_edit_session(
        db: Session,
        project_id: str,
        case_id: str,
        actor_id: str,
    ) -> TestCaseEditSession:
        """启动或幂等进入一个用例的编辑会话"""
        actor_uuid = uuid.UUID(str(actor_id))

        case = TestCaseService._get_project_case(db, project_id, case_id)

        # 检查是否已有开放会话
        stmt = select(TestCaseEditSession).where(
            TestCaseEditSession.case_id == case.id, TestCaseEditSession.status == "OPEN"
        )
        existing_sessions = db.scalars(stmt).all()

        for sess in existing_sessions:
            if sess.actor_id == actor_uuid:
                # 幂等返回自己已有的会话
                return sess
            else:
                # 其他人的会话在有效期内则冲突
                # 默认设 30 分钟内活跃的会话算冲突
                last_act = sess.last_activity_at
                if last_act.tzinfo is None:
                    last_act = last_act.replace(tzinfo=UTC)
                active_limit = datetime.now(UTC) - last_act
                if active_limit.total_seconds() < 1800:
                    raise AppError(
                        code="CASE_EDIT_SESSION_CONFLICT",
                        message="其他成员正在编辑此用例中，无法进入",
                        status_code=409,
                    )

        # 新开一个会话
        session = TestCaseEditSession(
            case_id=case.id,
            actor_id=actor_uuid,
            base_revision_id=case.current_revision_id,
            base_row_version=case.row_version,
            status="OPEN",
            dirty_fields={},
        )
        db.add(session)
        db.flush()
        return session

    @staticmethod
    def update_session_draft(
        db: Session,
        project_id: str,
        case_id: str,
        session_id: str,
        dirty_fields: dict[str, Any],
        actor_id: str,
    ) -> TestCaseEditSession:
        """暂存草稿，合并更新 dirty_fields"""
        actor_uuid = uuid.UUID(str(actor_id))

        session = TestCaseService._get_open_project_session(
            db,
            project_id=project_id,
            case_id=case_id,
            session_id=session_id,
        )

        if session.actor_id != actor_uuid:
            raise AppError(
                code="EDIT_SESSION_FORBIDDEN", message="无权更新该会话草稿", status_code=403
            )

        # 合并 dirty_fields
        current_dirty = dict(session.dirty_fields or {})
        for k, v in dirty_fields.items():
            current_dirty[k] = v

        session.dirty_fields = current_dirty
        session.last_activity_at = utc_now()
        db.flush()
        return session

    @staticmethod
    def finalize_edit_session(
        db: Session,
        project_id: str,
        case_id: str,
        session_id: str,
        actor_id: str,
        change_summary: dict[str, Any],
    ) -> TestCaseRevision:
        """合并提交并发布编辑会话，产生新修订快照"""
        actor_uuid = uuid.UUID(str(actor_id))

        session = TestCaseService._get_open_project_session(
            db,
            project_id=project_id,
            case_id=case_id,
            session_id=session_id,
        )

        if session.actor_id != actor_uuid:
            raise AppError(
                code="EDIT_SESSION_FORBIDDEN", message="无权提交该编辑会话", status_code=403
            )

        case = TestCaseService._get_project_case(db, project_id, case_id)

        # 乐观锁校验
        if case.row_version != session.base_row_version:
            raise AppError(
                code="CASE_OPTIMISTIC_LOCK_CONFLICT",
                message="用例在编辑期间已被其他成员修改，请重新拉取",
                status_code=409,
            )

        dirty = session.dirty_fields or {}

        # 仅将允许更新的字段合并回 TestCase
        allowed_fields = [
            "title",
            "precondition",
            "priority",
            "case_type",
            "tags_json",
            "test_data_note",
            "note",
        ]

        for field in allowed_fields:
            if field in dirty:
                val = dirty[field]
                if field == "title":
                    val = str(val).strip()
                setattr(case, field, val)

        # 如果更新了 steps
        if "steps" in dirty:
            # 1. 删除旧步骤
            db.execute(delete(TestCaseStep).where(TestCaseStep.case_id == case.id))
            # 2. 插入新步骤
            steps_list = dirty["steps"]
            if not isinstance(steps_list, list):
                raise AppError(
                    code="INVALID_STEPS_FORMAT", message="步骤格式必须为数组", status_code=400
                )

            for idx, s in enumerate(steps_list, start=1):
                step = TestCaseStep(
                    case_id=case.id,
                    step_order=idx,
                    action=str(s.get("action", "")).strip(),
                    expected_result=str(s.get("expected_result", "")).strip(),
                    note=s.get("note"),
                )
                db.add(step)

        # 即使没有任何内容变更，依然为了版本号前进和记录 Revision 判定为有变化
        case.row_version += 1
        case.updated_by = actor_uuid
        case.updated_at = utc_now()
        db.flush()

        # 读取最终步骤，打包 snapshot
        steps_stmt = (
            select(TestCaseStep)
            .where(TestCaseStep.case_id == case.id)
            .order_by(TestCaseStep.step_order)
        )
        db_steps = db.scalars(steps_stmt).all()

        snapshot = {
            "title": case.title,
            "precondition": case.precondition,
            "priority": case.priority,
            "case_type": case.case_type,
            "tags_json": case.tags_json,
            "test_data_note": case.test_data_note,
            "note": case.note,
            "steps": [
                {
                    "step_order": s.step_order,
                    "action": s.action,
                    "expected_result": s.expected_result,
                    "note": s.note,
                }
                for s in db_steps
            ],
        }
        serialized_snapshot = json.dumps(snapshot, sort_keys=True)
        snapshot_hash = hashlib.sha256(serialized_snapshot.encode("utf-8")).hexdigest()

        # 获取最大 revision_no
        rev_stmt = (
            select(TestCaseRevision.revision_no)
            .where(TestCaseRevision.case_id == case.id)
            .order_by(TestCaseRevision.revision_no.desc())
            .limit(1)
        )
        max_rev = db.scalar(rev_stmt) or 0
        new_rev_no = max_rev + 1

        revision = TestCaseRevision(
            case_id=case.id,
            revision_no=new_rev_no,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
            change_summary=change_summary,
            edit_session_id=session.id,
            created_by=actor_uuid,
        )
        db.add(revision)
        db.flush()

        case.current_revision_id = revision.id

        # 变变成 FINALIZED 状态
        session.status = "FINALIZED"
        session.finalized_at = utc_now()
        db.flush()

        return revision

    @staticmethod
    def resolve_stable_revisions_for_source_task(
        db: Session,
        project_id: str,
        source_design_task_id: str,
        actor_id: str,
    ) -> list[dict[str, Any]]:
        """M06 集成合约：返回来源设计任务当前全部有效用例的稳定修订快照。

        会 finalize 仍在 OPEN 的编辑会话以取得稳定修订；任意用例缺失稳定修订
        或存在无法解决的编辑会话冲突时整体失败，不静默跳过。
        """
        proj_uuid = uuid.UUID(str(project_id))
        task_uuid = uuid.UUID(str(source_design_task_id))

        case_stmt = select(TestCase).where(
            TestCase.project_id == proj_uuid,
            TestCase.source_task_id == task_uuid,
            TestCase.deleted_at.is_(None),
        )
        cases = db.scalars(case_stmt).all()
        if not cases:
            raise AppError(
                code="EXECUTION_SOURCE_TASK_HAS_NO_CASES",
                message="来源用例设计任务当前没有有效用例，无法创建执行任务",
                status_code=400,
            )

        # 预取模块关系与模块，构建 modulePaths
        case_ids = [c.id for c in cases]
        rel_stmt = select(TestCaseModuleRelation).where(
            TestCaseModuleRelation.case_id.in_(case_ids)
        )
        relations = db.scalars(rel_stmt).all()
        module_ids = {r.module_id for r in relations}
        mod_stmt = select(CaseModule).where(CaseModule.id.in_(module_ids))
        modules = db.scalars(mod_stmt).all()
        module_by_id = {m.id: m for m in modules}
        case_modules: dict[uuid.UUID, list[uuid.UUID]] = {}
        for r in relations:
            case_modules.setdefault(r.case_id, []).append(r.module_id)

        def build_module_paths(mids: list[uuid.UUID]) -> list[str]:
            paths: list[str] = []
            for mid in mids:
                m = module_by_id.get(mid)
                if not m:
                    continue
                chain: list[str] = []
                cur: CaseModule | None = m
                seen: set[uuid.UUID] = set()
                while cur is not None and cur.id not in seen:
                    seen.add(cur.id)
                    chain.append(cur.name)
                    if cur.parent_id and cur.parent_id in module_by_id:
                        cur = module_by_id[cur.parent_id]
                    else:
                        cur = None
                chain.reverse()
                paths.append(" / ".join(chain))
            return paths

        results: list[dict[str, Any]] = []
        for case in cases:
            if case.current_revision_id is None:
                raise AppError(
                    code="EXECUTION_SCOPE_SNAPSHOT_FAILED",
                    message=f"用例 {case.case_no} 缺少稳定修订，无法冻结执行范围",
                    status_code=400,
                )

            # finalize 仍在 OPEN 的编辑会话，聚合为稳定修订
            open_stmt = select(TestCaseEditSession).where(
                TestCaseEditSession.case_id == case.id,
                TestCaseEditSession.status == "OPEN",
            )
            open_sessions = db.scalars(open_stmt).all()
            for sess in open_sessions:
                try:
                    TestCaseService.finalize_edit_session(
                        db,
                        project_id,
                        str(case.id),
                        str(sess.id),
                        str(sess.actor_id),
                        {
                            "type": "EXECUTION_FINALIZE",
                            "note": "创建执行任务前聚合未提交的编辑会话",
                        },
                    )
                except AppError as err:
                    raise AppError(
                        code="EXECUTION_SCOPE_SNAPSHOT_FAILED",
                        message=f"用例 {case.case_no} 存在无法聚合的编辑会话，无法冻结执行范围",
                        status_code=400,
                    ) from err

            # 重新读取 finalize 后的用例与稳定修订
            refreshed = db.get(TestCase, case.id)
            assert refreshed is not None
            case = refreshed
            revision = db.get(TestCaseRevision, case.current_revision_id)
            if revision is None:
                raise AppError(
                    code="EXECUTION_SCOPE_SNAPSHOT_FAILED",
                    message=f"用例 {case.case_no} 的稳定修订不存在",
                    status_code=400,
                )

            snapshot = revision.snapshot
            enriched = {
                "caseNo": case.case_no,
                "title": snapshot.get("title"),
                "modulePaths": build_module_paths(case_modules.get(case.id, [])),
                "precondition": snapshot.get("precondition"),
                "priority": snapshot.get("priority"),
                "caseType": snapshot.get("case_type"),
                "tags": snapshot.get("tags_json"),
                "testDataNote": snapshot.get("test_data_note"),
                "note": snapshot.get("note"),
                "steps": snapshot.get("steps", []),
                "sourceDesignTaskId": str(task_uuid),
                "sourceRequirementId": None,
                "revisionNo": revision.revision_no,
                "revisionCreatedAt": (
                    revision.created_at.isoformat() if revision.created_at else None
                ),
            }
            results.append(
                {
                    "test_case_id": str(case.id),
                    "revision_id": str(revision.id),
                    "snapshot": enriched,
                    "snapshot_hash": revision.snapshot_hash,
                }
            )
        return results

    @staticmethod
    def abandon_edit_session(
        db: Session,
        project_id: str,
        case_id: str,
        session_id: str,
        actor_id: str,
    ) -> TestCaseEditSession:
        """放弃会话，置状态为 ABANDONED"""
        actor_uuid = uuid.UUID(str(actor_id))

        session = TestCaseService._get_open_project_session(
            db,
            project_id=project_id,
            case_id=case_id,
            session_id=session_id,
        )

        if session.actor_id != actor_uuid:
            raise AppError(
                code="EDIT_SESSION_FORBIDDEN", message="无权操作该编辑会话", status_code=403
            )

        session.status = "ABANDONED"
        db.flush()
        return session


class CaseModuleService:
    @staticmethod
    def _get_active_project_module(
        db: Session,
        project_id: str,
        module_id: str,
    ) -> CaseModule:
        proj_uuid = uuid.UUID(str(project_id))
        mod_uuid = uuid.UUID(str(module_id))
        stmt = select(CaseModule).where(
            CaseModule.id == mod_uuid,
            CaseModule.project_id == proj_uuid,
            CaseModule.archived_at.is_(None),
        )
        module = db.scalar(stmt)
        if not module:
            raise AppError(
                code="CASE_MODULE_NOT_FOUND", message="用例模块不存在或已归档", status_code=404
            )
        return module

    @staticmethod
    def get_module_tree(db: Session, project_id: str) -> list[dict[str, Any]]:
        """获取项目的所有未归档模块树"""
        proj_uuid = uuid.UUID(str(project_id))
        stmt = (
            select(CaseModule)
            .where(CaseModule.project_id == proj_uuid, CaseModule.archived_at.is_(None))
            .order_by(CaseModule.sort_order.asc(), CaseModule.name.asc())
        )
        modules = db.scalars(stmt).all()

        # 构建 id -> node 映射
        nodes = {
            m.id: {
                "id": str(m.id),
                "projectId": str(m.project_id),
                "parentId": str(m.parent_id) if m.parent_id else None,
                "name": m.name,
                "description": m.description,
                "sortOrder": m.sort_order,
                "children": [],
            }
            for m in modules
        }

        roots = []
        for m in modules:
            node = nodes[m.id]
            if m.parent_id and m.parent_id in nodes:
                nodes[m.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    @staticmethod
    def create_module(
        db: Session,
        project_id: str,
        name: str,
        parent_id: str | None = None,
        description: str | None = None,
        sort_order: int = 0,
    ) -> CaseModule:
        """创建用例模块"""
        proj_uuid = uuid.UUID(str(project_id))
        parent_uuid = uuid.UUID(str(parent_id)) if parent_id else None

        # 校验项目
        project = db.get(Project, proj_uuid)
        if not project:
            raise AppError(code="PROJECT_NOT_FOUND", message="关联项目不存在", status_code=404)

        # 校验父模块
        if parent_uuid:
            CaseModuleService._get_active_project_module(db, project_id, str(parent_uuid))

        # 唯一性校验（同父模块下名称不能重复）
        name_clean = name.strip()
        stmt = select(CaseModule).where(
            CaseModule.project_id == proj_uuid,
            CaseModule.parent_id == parent_uuid,
            CaseModule.name == name_clean,
            CaseModule.archived_at.is_(None),
        )
        existing = db.scalar(stmt)
        if existing:
            raise AppError(
                code="CASE_MODULE_NAME_DUPLICATED",
                message="同父节点下已存在同名模块",
                status_code=409,
            )

        module = CaseModule(
            project_id=proj_uuid,
            parent_id=parent_uuid,
            name=name_clean,
            description=description,
            sort_order=sort_order,
        )
        db.add(module)
        db.flush()
        return module

    @staticmethod
    def update_module(
        db: Session,
        project_id: str,
        module_id: str,
        name: str,
        description: str | None = None,
        sort_order: int = 0,
    ) -> CaseModule:
        """修改模块基本信息"""
        mod_uuid = uuid.UUID(str(module_id))
        module = CaseModuleService._get_active_project_module(db, project_id, module_id)

        name_clean = name.strip()
        # 唯一性校验
        stmt = select(CaseModule).where(
            CaseModule.project_id == module.project_id,
            CaseModule.parent_id == module.parent_id,
            CaseModule.id != mod_uuid,
            CaseModule.name == name_clean,
            CaseModule.archived_at.is_(None),
        )
        existing = db.scalar(stmt)
        if existing:
            raise AppError(
                code="CASE_MODULE_NAME_DUPLICATED",
                message="同父节点下已存在同名模块",
                status_code=409,
            )

        module.name = name_clean
        module.description = description
        module.sort_order = sort_order
        db.flush()
        return module

    @staticmethod
    def move_module(
        db: Session,
        project_id: str,
        module_id: str,
        target_parent_id: str | None,
    ) -> CaseModule:
        """移动模块，支持父子移动的循环依赖检测"""
        proj_uuid = uuid.UUID(str(project_id))
        mod_uuid = uuid.UUID(str(module_id))
        target_uuid = uuid.UUID(str(target_parent_id)) if target_parent_id else None

        module = CaseModuleService._get_active_project_module(db, project_id, module_id)

        if target_uuid:
            CaseModuleService._get_active_project_module(db, project_id, str(target_uuid))

        if mod_uuid == target_uuid:
            raise AppError(
                code="CASE_MODULE_CYCLIC_DEPENDENCY",
                message="目标父节点不能是模块本身",
                status_code=400,
            )

        # 循环依赖检测：追溯 target_parent_id 的祖先路径，若存在 module_id 则冲突
        curr_uuid = target_uuid
        visited = set()
        while curr_uuid:
            if curr_uuid == mod_uuid:
                raise AppError(
                    code="CASE_MODULE_CYCLIC_DEPENDENCY",
                    message="不能将模块移动到自己的子模块下",
                    status_code=400,
                )
            if curr_uuid in visited:
                break
            visited.add(curr_uuid)
            parent_stmt = select(CaseModule).where(
                CaseModule.id == curr_uuid,
                CaseModule.project_id == proj_uuid,
                CaseModule.archived_at.is_(None),
            )
            parent_mod = db.scalar(parent_stmt)
            if not parent_mod:
                raise AppError(
                    code="CASE_MODULE_NOT_FOUND",
                    message="用例模块不存在或已归档",
                    status_code=404,
                )
            curr_uuid = parent_mod.parent_id

        # 唯一性校验（目标父模块下不能重名）
        stmt = select(CaseModule).where(
            CaseModule.project_id == module.project_id,
            CaseModule.parent_id == target_uuid,
            CaseModule.id != mod_uuid,
            CaseModule.name == module.name,
            CaseModule.archived_at.is_(None),
        )
        existing = db.scalar(stmt)
        if existing:
            raise AppError(
                code="CASE_MODULE_NAME_DUPLICATED",
                message="目标父节点下已存在同名模块",
                status_code=409,
            )

        module.parent_id = target_uuid
        db.flush()
        return module

    @staticmethod
    def archive_module(db: Session, project_id: str, module_id: str) -> CaseModule:
        """归档模块，受防空归档限制（有子模块或有用例则禁止归档）"""
        proj_uuid = uuid.UUID(str(project_id))
        mod_uuid = uuid.UUID(str(module_id))
        module = CaseModuleService._get_active_project_module(db, project_id, module_id)

        # 检查是否含有未归档的子模块
        child_stmt = select(CaseModule).where(
            CaseModule.project_id == proj_uuid,
            CaseModule.parent_id == mod_uuid,
            CaseModule.archived_at.is_(None),
        )
        has_child = db.scalar(child_stmt)
        if has_child:
            raise AppError(
                code="CASE_MODULE_HAS_CHILDREN",
                message="该模块下仍有子模块，禁止归档",
                status_code=400,
            )

        # 检查是否有关联用例
        has_cases = (
            db.scalar(
                select(TestCaseModuleRelation)
                .where(TestCaseModuleRelation.module_id == mod_uuid)
                .limit(1)
            )
            is not None
        )
        if has_cases:
            raise AppError(
                code="CASE_MODULE_HAS_TEST_CASES",
                message="该模块下仍有关联测试用例，禁止归档",
                status_code=400,
            )

        module.archived_at = utc_now()
        db.flush()
        return module


class CaseMindmapService:
    @staticmethod
    def get_or_create_mindmap(
        db: Session,
        project_id: str,
        task_id: str,
    ) -> TestCaseMindmap:
        """获取或创建任务关联的脑图"""
        _get_active_case_design_task(db, project_id, task_id)
        proj_uuid = uuid.UUID(str(project_id))
        task_uuid = uuid.UUID(str(task_id))

        stmt = select(TestCaseMindmap).where(
            TestCaseMindmap.project_id == proj_uuid,
            TestCaseMindmap.task_id == task_uuid,
        )
        mindmap = db.scalar(stmt)
        if not mindmap:
            # 静默创建空脑图结构
            default_data = {
                "nodeData": {
                    "id": "root",
                    "topic": "测试用例脑图",
                    "root": True,
                }
            }
            mindmap = TestCaseMindmap(
                project_id=proj_uuid,
                task_id=task_uuid,
                title="新测试点脑图",
                data=default_data,
            )
            db.add(mindmap)
            db.flush()
        return mindmap

    @staticmethod
    def save_mindmap(
        db: Session,
        project_id: str,
        task_id: str,
        title: str,
        data: dict[str, Any],
    ) -> TestCaseMindmap:
        """保存脑图最新数据"""
        _get_active_case_design_task(db, project_id, task_id)
        proj_uuid = uuid.UUID(str(project_id))
        task_uuid = uuid.UUID(str(task_id))

        stmt = select(TestCaseMindmap).where(
            TestCaseMindmap.project_id == proj_uuid,
            TestCaseMindmap.task_id == task_uuid,
        )
        mindmap = db.scalar(stmt)
        if not mindmap:
            mindmap = TestCaseMindmap(
                project_id=proj_uuid,
                task_id=task_uuid,
                title=title,
                data=data,
            )
            db.add(mindmap)
        else:
            mindmap.title = title
            mindmap.data = data
        db.flush()
        return mindmap

    @staticmethod
    def sync_mindmap_to_cases(
        db: Session,
        project_id: str,
        task_id: str,
        actor_id: str,
        request_id: str,
    ) -> int:
        """将脑图同步为测试用例列表"""
        _get_active_case_design_task(db, project_id, task_id)
        proj_uuid = uuid.UUID(str(project_id))
        task_uuid = uuid.UUID(str(task_id))

        # 1. 查找脑图
        stmt = select(TestCaseMindmap).where(
            TestCaseMindmap.project_id == proj_uuid,
            TestCaseMindmap.task_id == task_uuid,
        )
        mindmap = db.scalar(stmt)
        if not mindmap:
            return 0

        # 2. 提取叶子节点路径
        node_data = mindmap.data.get("nodeData", {})
        if not node_data:
            return 0

        def extract_leaf_paths(
            node: dict[str, Any], current_path: list[str]
        ) -> list[tuple[list[str], str]]:
            topic = node.get("topic", "")
            children = node.get("children", [])
            if not children:
                return [(current_path, topic)]
            new_path = [*current_path, topic]
            results = []
            for child in children:
                results.extend(extract_leaf_paths(child, new_path))
            return results

        leaf_paths = extract_leaf_paths(node_data, [])

        # 3. 删除此前在该任务下由脑图同步生成的所有旧用例 (防止重复)
        del_stmt = select(TestCase).where(
            TestCase.project_id == proj_uuid, TestCase.source_task_id == task_uuid
        )
        old_cases = db.scalars(del_stmt).all()
        for oc in old_cases:
            db.delete(oc)
        db.flush()

        # 4. 批量生成新用例
        count = 0
        for parent_path, leaf_topic in leaf_paths:
            # 拼接用例标题：如果父级节点丰富，去掉根节点 "测试用例脑图"
            useful_parents = parent_path[1:] if len(parent_path) > 1 else parent_path
            title = "-".join([*useful_parents, leaf_topic])
            precondition = f"脑图路径: {' > '.join(parent_path)}"

            # 组装操作步骤
            step_text = f"按照脑图分支指引操作: {' -> '.join(parent_path)}"
            expected = leaf_topic

            steps = [
                {
                    "stepNo": 1,
                    "actions": step_text,
                    "expectedResults": expected,
                }
            ]

            TestCaseService.create_case(
                db=db,
                project_id=project_id,
                title=title,
                precondition=precondition,
                priority="MEDIUM",
                case_type="FUNCTIONAL",
                tags_json=["mindmap-sync"],
                test_data_note=None,
                note="由脑图一键同步生成",
                steps=steps,
                source_task_id=task_id,
                actor_id=actor_id,
                request_id=request_id,
                module_ids=None,
            )
            count += 1

        db.flush()
        return count
