import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    ExecutionTaskProfile,
    ProjectMember,
    Requirement,
    TestTask,
    TestTaskBlockage,
    TestTaskParticipant,
    TestTaskRequirement,
    TestTaskStatusHistory,
    User,
    Version,
)
from testweave.modules.audit.service import AuditService


class TestTaskService:
    @staticmethod
    def generate_next_task_no(db: Session, project_id: str) -> str:
        """根据项目内已有任务自动计算生成下一个 TASK-XXXXXX 单号"""
        stmt = select(TestTask.task_no).where(TestTask.project_id == uuid.UUID(str(project_id)))
        existing_nos = db.scalars(stmt).all()

        max_num = 0
        pattern = re.compile(r"(?i)^TASK-(\d+)$")
        for no in existing_nos:
            match = pattern.match(no.strip())
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

        return f"TASK-{max_num + 1:06d}"

    @staticmethod
    def get_task_by_id(db: Session, project_id: str, task_id: str) -> TestTask:
        """获取任务详情，严格校验项目隔离"""
        stmt = select(TestTask).where(
            TestTask.id == uuid.UUID(str(task_id)),
            TestTask.project_id == uuid.UUID(str(project_id)),
        )
        task = db.scalar(stmt)
        if not task:
            raise AppError(
                code="TEST_TASK_NOT_FOUND", message="测试任务不存在或无权限访问", status_code=404
            )
        return task

    @staticmethod
    def _validate_owner(db: Session, project_id: str, owner_id: str) -> None:
        """校验负责人是否为本项目有效成员"""
        member_stmt = select(ProjectMember).where(
            ProjectMember.project_id == uuid.UUID(str(project_id)),
            ProjectMember.user_id == uuid.UUID(str(owner_id)),
        )
        if not db.scalar(member_stmt):
            raise AppError(
                code="TEST_TASK_OWNER_INVALID",
                message="负责人不是该项目的有效成员",
                status_code=400,
            )

    @staticmethod
    def _validate_times(
        db: Session, planned_start_at: datetime, planned_end_at: datetime, version: Version
    ) -> None:
        """校验任务时间是否合规"""
        start_naive = (
            planned_start_at.replace(tzinfo=None) if planned_start_at.tzinfo else planned_start_at
        )
        end_naive = planned_end_at.replace(tzinfo=None) if planned_end_at.tzinfo else planned_end_at

        if end_naive <= start_naive:
            raise AppError(
                code="TEST_TASK_DATE_INVALID",
                message="任务计划结束时间不能早于计划开始时间",
                status_code=400,
            )

        # 校验版本上限
        if version.planned_end_at:
            version_end_naive = (
                version.planned_end_at.replace(tzinfo=None)
                if version.planned_end_at.tzinfo
                else version.planned_end_at
            )
            if end_naive > version_end_naive:
                raise AppError(
                    code="TEST_TASK_END_AFTER_VERSION_END",
                    message="任务计划结束时间不能晚于版本截止时间",
                    status_code=400,
                )

    @staticmethod
    def create_task(
        db: Session,
        project_id: str,
        version_id: str,
        task_type: str,
        title: str,
        description: str | None,
        priority: str,
        owner_id: str,
        planned_start_at: datetime | None,
        planned_end_at: datetime,
        test_goal: str | None,
        excluded_scope: str | None,
        tags_json: list[str] | None,
        actor_id: str,
        request_id: str,
        requirement_id: str | None = None,
    ) -> TestTask:
        # 1. 限制执行任务创建
        if task_type == "TEST_EXECUTION":
            raise AppError(
                code="TEST_EXECUTION_MODULE_NOT_AVAILABLE",
                message="用例执行模块尚未接入，当前无法创建用例执行任务",
                status_code=400,
            )

        if task_type != "CASE_DESIGN":
            raise AppError(
                code="TEST_TASK_TYPE_NOT_SUPPORTED",
                message=f"不支持的任务类型: {task_type}",
                status_code=400,
            )

        # 2. 读取并校验版本
        version_stmt = select(Version).where(
            Version.id == uuid.UUID(str(version_id)),
            Version.project_id == uuid.UUID(str(project_id)),
        )
        version = db.scalar(version_stmt)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="所属版本不存在", status_code=404)

        if version.status == "ARCHIVED":
            raise AppError(
                code="TEST_TASK_VERSION_ARCHIVED",
                message="所属版本已归档，无法创建任务",
                status_code=400,
            )

        # 3. 时间校验
        now_time = datetime.now(UTC)
        start_at = planned_start_at if planned_start_at else now_time
        TestTaskService._validate_times(db, start_at, planned_end_at, version)

        # 4. 负责人校验
        TestTaskService._validate_owner(db, project_id, owner_id)

        # 5. 生成单号
        task_no = TestTaskService.generate_next_task_no(db, project_id)

        # 6. 新建任务
        task = TestTask(
            project_id=uuid.UUID(str(project_id)),
            version_id=uuid.UUID(str(version_id)),
            task_no=task_no,
            task_type=task_type,
            status="DRAFT",
            title=title.strip(),
            description=description,
            priority=priority,
            owner_id=uuid.UUID(str(owner_id)),
            planned_start_at=start_at,
            planned_end_at=planned_end_at,
            test_goal=test_goal,
            excluded_scope=excluded_scope,
            tags_json=tags_json,
            row_version=1,
            created_by=uuid.UUID(str(actor_id)),
        )
        db.add(task)
        db.flush()

        # 关联需求
        if task_type == "CASE_DESIGN":
            if not requirement_id:
                raise AppError(
                    code="TEST_TASK_REQUIREMENT_REQUIRED",
                    message="用例设计任务必须关联一个有效需求",
                    status_code=400,
                )

            req_stmt = select(Requirement).where(
                Requirement.id == uuid.UUID(str(requirement_id)),
                Requirement.project_id == uuid.UUID(str(project_id)),
            )
            req = db.scalar(req_stmt)
            if not req:
                raise AppError(
                    code="TEST_TASK_REQUIREMENT_INVALID",
                    message="关联的需求无效或不属于当前项目",
                    status_code=400,
                )

            link = TestTaskRequirement(
                task_id=task.id,
                requirement_id=req.id,
                linked_by=uuid.UUID(str(actor_id)),
            )
            db.add(link)
            db.flush()

        # 记录初始状态历史
        history = TestTaskStatusHistory(
            project_id=uuid.UUID(str(project_id)),
            task_id=task.id,
            from_status="NONE",
            to_status="DRAFT",
            actor_id=uuid.UUID(str(actor_id)),
            request_id=request_id,
        )
        db.add(history)
        db.flush()

        AuditService.log_event(
            db,
            action="test_task.created",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"创建测试任务 '{task.title}' (编号: {task.task_no})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

        return task

    @staticmethod
    def update_task(
        db: Session,
        project_id: str,
        task_id: str,
        title: str,
        description: str | None,
        priority: str,
        owner_id: str,
        planned_start_at: datetime,
        planned_end_at: datetime,
        test_goal: str | None,
        excluded_scope: str | None,
        tags_json: list[str] | None,
        expected_row_version: int,
        actor_id: str,
        request_id: str,
    ) -> TestTask:
        task = TestTaskService.get_task_by_id(db, project_id, task_id)

        # 1. 乐观锁校验
        if task.row_version != expected_row_version:
            raise AppError(
                code="OPTIMISTIC_LOCK_CONFLICT",
                message="当前任务已被其他用户修改，请刷新后重试",
                status_code=409,
            )

        # 2. 写保护校验
        if task.status in ["COMPLETED", "ARCHIVED"]:
            raise AppError(
                code="TEST_TASK_ARCHIVED_READ_ONLY",
                message="任务已完成或归档，处于只读状态。若需修改范围或基础信息，请先重新打开",
                status_code=400,
            )

        # 3. 负责人校验
        TestTaskService._validate_owner(db, project_id, owner_id)

        # 4. 时间校验
        version = db.get(Version, task.version_id)
        assert version is not None
        TestTaskService._validate_times(db, planned_start_at, planned_end_at, version)

        # 5. 更新字段
        task.title = title.strip()
        task.description = description
        task.priority = priority
        task.owner_id = uuid.UUID(str(owner_id))
        task.planned_start_at = planned_start_at
        task.planned_end_at = planned_end_at
        task.test_goal = test_goal
        task.excluded_scope = excluded_scope
        task.tags_json = tags_json
        task.row_version += 1
        task.updated_by = uuid.UUID(str(actor_id))

        db.flush()

        AuditService.log_event(
            db,
            action="test_task.updated",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"更新测试任务 '{task.title}' (编号: {task.task_no})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

        return task

    @staticmethod
    def update_requirements(
        db: Session,
        project_id: str,
        task_id: str,
        requirement_id: str | None,
        actor_id: str,
        request_id: str,
    ) -> list[dict]:
        """维护任务关联需求，返回非阻断的重复关联警告列表"""
        task = TestTaskService.get_task_by_id(db, project_id, task_id)

        if task.status in ["COMPLETED", "ARCHIVED"]:
            raise AppError(
                code="TEST_TASK_ARCHIVED_READ_ONLY",
                message="任务已完成或归档，处于只读状态。若需修改范围或基础信息，请先重新打开",
                status_code=400,
            )

        if task.task_type == "CASE_DESIGN" and not requirement_id:
            raise AppError(
                code="TEST_TASK_REQUIREMENT_REQUIRED",
                message="用例设计任务必须且只能关联一个有效需求",
                status_code=400,
            )

        # 校验需求有效性
        valid_reqs = []
        if requirement_id:
            req_uuid = uuid.UUID(str(requirement_id))
            stmt = select(Requirement).where(
                Requirement.id == req_uuid, Requirement.project_id == uuid.UUID(str(project_id))
            )
            req = db.scalar(stmt)
            if not req:
                raise AppError(
                    code="TEST_TASK_REQUIREMENT_INVALID",
                    message="关联的需求无效或不属于当前项目",
                    status_code=400,
                )
            valid_reqs.append(req)

        # 检查重复设计任务提醒
        warnings = []
        for req in valid_reqs:
            conflict_stmt = (
                select(TestTask)
                .join(TestTaskRequirement, TestTaskRequirement.task_id == TestTask.id)
                .where(
                    TestTaskRequirement.requirement_id == req.id,
                    TestTask.task_type == "CASE_DESIGN",
                    TestTask.status.not_in(["COMPLETED", "CANCELLED", "ARCHIVED"]),
                    TestTask.id != task.id,
                )
            )
            conflict_tasks = db.scalars(conflict_stmt).all()
            for ct in conflict_tasks:
                # 获取负责人名字
                owner_user = db.get(User, ct.owner_id)
                owner_name = owner_user.display_name if owner_user else str(ct.owner_id)
                warnings.append(
                    {
                        "requirementNo": req.requirement_no,
                        "requirementTitle": req.title,
                        "taskId": str(ct.id),
                        "taskNo": ct.task_no,
                        "taskTitle": ct.title,
                        "ownerName": owner_name,
                        "status": ct.status,
                    }
                )

        # 清除旧绑定，绑定新关联
        db.query(TestTaskRequirement).filter(TestTaskRequirement.task_id == task.id).delete()

        for req in valid_reqs:
            link = TestTaskRequirement(
                task_id=task.id,
                requirement_id=req.id,
                linked_by=uuid.UUID(str(actor_id)),
            )
            db.add(link)

        # 乐观锁升级
        task.row_version += 1
        db.flush()

        AuditService.log_event(
            db,
            action="test_task.requirements_updated",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"更新了测试任务 '{task.title}' 的需求范围 (关联数: {len(valid_reqs)})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

        return warnings

    @staticmethod
    def update_participants(
        db: Session,
        project_id: str,
        task_id: str,
        user_ids: list[str],
        actor_id: str,
        request_id: str,
    ) -> None:
        task = TestTaskService.get_task_by_id(db, project_id, task_id)

        if task.status in ["COMPLETED", "ARCHIVED"]:
            raise AppError(
                code="TEST_TASK_ARCHIVED_READ_ONLY",
                message="任务已完成或归档，处于只读状态。若需修改参与人，请先重新打开",
                status_code=400,
            )

        # 过滤/去重负责人
        filtered_user_ids = [uid for uid in user_ids if uuid.UUID(uid) != task.owner_id]
        unique_user_ids = list(set(filtered_user_ids))

        # 校验成员合法性
        user_uuids = [uuid.UUID(str(uid)) for uid in unique_user_ids]
        if user_uuids:
            member_stmt = select(ProjectMember).where(
                ProjectMember.project_id == uuid.UUID(str(project_id)),
                ProjectMember.user_id.in_(user_uuids),
            )
            valid_members = db.scalars(member_stmt).all()
            if len(valid_members) != len(user_uuids):
                raise AppError(
                    code="TEST_TASK_PARTICIPANT_INVALID",
                    message="部分参与人不是该项目的有效成员",
                    status_code=400,
                )

        # 清除旧绑定并重建
        db.query(TestTaskParticipant).filter(TestTaskParticipant.task_id == task.id).delete()

        for uuid_val in user_uuids:
            participant = TestTaskParticipant(
                task_id=task.id,
                user_id=uuid_val,
                added_by=uuid.UUID(str(actor_id)),
            )
            db.add(participant)

        # 乐观锁升级
        task.row_version += 1
        db.flush()

        AuditService.log_event(
            db,
            action="test_task.participants_updated",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"更新了测试任务 '{task.title}' 的参与人列表 (参与人数: {len(user_uuids)})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

    @staticmethod
    def transition_status(
        db: Session,
        project_id: str,
        task_id: str,
        target_status: str,
        reason_code: str | None,
        reason_text: str | None,
        expected_row_version: int,
        actor_id: str,
        request_id: str,
        is_admin_or_lead: bool = False,
    ) -> TestTask:
        task = TestTaskService.get_task_by_id(db, project_id, task_id)

        # 1. 乐观锁校验
        if task.row_version != expected_row_version:
            raise AppError(
                code="OPTIMISTIC_LOCK_CONFLICT",
                message="当前任务已被其他用户修改，请刷新后重试",
                status_code=409,
            )

        # 2. 状态机转移校验
        from_status = task.status
        if from_status == target_status:
            return task  # 状态一致直接返回

        # 归档只读策略（只能通过 ARCHIVED 恢复来变更状态）
        if from_status == "ARCHIVED" and target_status != "previous_status":
            raise AppError(
                code="TEST_TASK_ARCHIVED_READ_ONLY",
                message="已归档任务为只读状态，无法直接修改状态",
                status_code=400,
            )

        # READY 前置校验
        if target_status == "READY":
            if not task.title:
                raise AppError(
                    code="TEST_TASK_TITLE_REQUIRED", message="任务标题不能为空", status_code=400
                )

            # 校验版本是否已归档
            version = db.get(Version, task.version_id)
            if version and version.status == "ARCHIVED":
                raise AppError(
                    code="TEST_TASK_VERSION_ARCHIVED",
                    message="所属版本已归档，无法流转任务状态",
                    status_code=400,
                )

            # 校验负责人
            TestTaskService._validate_owner(db, project_id, str(task.owner_id))

            if task.task_type == "CASE_DESIGN":
                # 校验必须且只能关联一个需求
                link_count = (
                    db.query(TestTaskRequirement)
                    .filter(TestTaskRequirement.task_id == task.id)
                    .count()
                )
                if link_count != 1:
                    raise AppError(
                        code="TEST_TASK_REQUIREMENT_REQUIRED",
                        message="用例设计任务必须且只能关联一个有效需求才能提交待开始",
                        status_code=400,
                    )
            elif task.task_type == "TEST_EXECUTION":
                # 执行任务进入待开始：必须已通过 M06 原子接口冻结完整执行范围
                profile = db.get(ExecutionTaskProfile, task.id)
                if profile is None or profile.total_count <= 0:
                    raise AppError(
                        code="TEST_EXECUTION_SCOPE_NOT_READY",
                        message="执行任务尚未冻结有效的执行范围，无法进入待开始状态",
                        status_code=400,
                    )

        # READY -> IN_PROGRESS
        if from_status == "READY" and target_status == "IN_PROGRESS" and not task.actual_started_at:
            task.actual_started_at = datetime.now(UTC)

        # IN_PROGRESS <-> BLOCKED
        if target_status == "BLOCKED":
            if from_status != "IN_PROGRESS":
                raise AppError(
                    code="TEST_TASK_INVALID_TRANSITION",
                    message=f"不能从 {from_status} 状态进入阻塞",
                    status_code=400,
                )
            if not reason_code or not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_BLOCK_REASON_REQUIRED",
                    message="阻塞状态下必须填写阻塞原因及说明",
                    status_code=400,
                )

            # 写入 Blockage 记录
            blockage = TestTaskBlockage(
                project_id=uuid.UUID(str(project_id)),
                task_id=task.id,
                reason_code=reason_code,
                description=reason_text.strip(),
                blocked_by=uuid.UUID(str(actor_id)),
            )
            db.add(blockage)

        if from_status == "BLOCKED" and target_status == "IN_PROGRESS":
            if not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_UNBLOCK_NOTE_REQUIRED",
                    message="解除阻塞必须填写解决说明",
                    status_code=400,
                )

            # 解决 blockage 记录
            blockage_stmt = (
                select(TestTaskBlockage)
                .where(TestTaskBlockage.task_id == task.id, TestTaskBlockage.resolved_at.is_(None))
                .order_by(desc(TestTaskBlockage.blocked_at))
            )
            blockage = db.scalar(blockage_stmt)
            if blockage:
                blockage.resolved_by = uuid.UUID(str(actor_id))
                blockage.resolved_at = datetime.now(UTC)
                blockage.resolution_note = reason_text.strip()

        # IN_PROGRESS -> COMPLETED
        if target_status == "COMPLETED":
            if from_status != "IN_PROGRESS":
                raise AppError(
                    code="TEST_TASK_INVALID_TRANSITION",
                    message=f"任务不能从 {from_status} 状态直接完成",
                    status_code=400,
                )

            # 检查是否有未解决阻塞
            active_blockage_stmt = select(TestTaskBlockage).where(
                TestTaskBlockage.task_id == task.id, TestTaskBlockage.resolved_at.is_(None)
            )
            if db.scalar(active_blockage_stmt):
                raise AppError(
                    code="TEST_TASK_HAS_ACTIVE_BLOCKAGE",
                    message="任务处于阻塞状态，无法完成",
                    status_code=400,
                )

            # 执行任务完成前必须所有用例至少执行一次
            if task.task_type == "TEST_EXECUTION":
                exec_profile = db.get(ExecutionTaskProfile, task.id)
                if exec_profile is None:
                    raise AppError(
                        code="EXECUTION_PROFILE_MISSING",
                        message="执行任务配置缺失，无法完成",
                        status_code=400,
                    )
                if exec_profile.not_run_count > 0:
                    raise AppError(
                        code="EXECUTION_COMPLETION_NOT_RUN_EXISTS",
                        message="仍有未执行的用例，无法完成任务",
                        status_code=400,
                    )

            task.current_completed_at = datetime.now(UTC)
            task.completion_count += 1
            task.completion_note = reason_text.strip() if reason_text else None

        # COMPLETED -> IN_PROGRESS (重新打开)
        if from_status == "COMPLETED" and target_status == "IN_PROGRESS":
            if not is_admin_or_lead:
                raise AppError(
                    code="FORBIDDEN",
                    message="只有测试负责人或项目管理员可重新打开已完成任务",
                    status_code=403,
                )
            if not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_REOPEN_REASON_REQUIRED",
                    message="重新打开已完成的任务必须填写重新打开原因",
                    status_code=400,
                )

            # 保留 current_completed_at 历史通过 status_history 查，主表清空
            task.current_completed_at = None

        # DRAFT/READY/IN_PROGRESS/BLOCKED -> CANCELLED
        if target_status == "CANCELLED":
            if from_status in ["COMPLETED", "ARCHIVED"]:
                raise AppError(
                    code="TEST_TASK_INVALID_TRANSITION",
                    message="任务已完成或归档，不能取消",
                    status_code=400,
                )
            if not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_CANCEL_REASON_REQUIRED",
                    message="取消任务必须填写原因",
                    status_code=400,
                )

            # 如果是BLOCKED取消，自动解决未解决的阻塞
            blockage_stmt = select(TestTaskBlockage).where(
                TestTaskBlockage.task_id == task.id, TestTaskBlockage.resolved_at.is_(None)
            )
            blockage = db.scalar(blockage_stmt)
            if blockage:
                blockage.resolved_by = uuid.UUID(str(actor_id))
                blockage.resolved_at = datetime.now(UTC)
                blockage.resolution_note = f"[任务取消自动闭合] {reason_text.strip()}"

        # CANCELLED -> DRAFT
        if from_status == "CANCELLED" and target_status == "DRAFT":
            if not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_RESTORE_REASON_REQUIRED",
                    message="恢复取消的任务必须填写原因",
                    status_code=400,
                )

            # 校验版本是否已归档
            version = db.get(Version, task.version_id)
            if version and version.status == "ARCHIVED":
                raise AppError(
                    code="TEST_TASK_VERSION_ARCHIVED",
                    message="所属版本已归档，无法恢复取消的任务",
                    status_code=400,
                )

        # COMPLETED/CANCELLED -> ARCHIVED (归档)
        if target_status == "ARCHIVED":
            if from_status not in ["COMPLETED", "CANCELLED"]:
                raise AppError(
                    code="TEST_TASK_INVALID_TRANSITION",
                    message="只有已完成或已取消的任务才可以进行归档",
                    status_code=400,
                )
            if not is_admin_or_lead:
                raise AppError(
                    code="FORBIDDEN",
                    message="只有项目管理员或测试负责人有权限归档任务",
                    status_code=403,
                )

            task.previous_status = from_status
            task.archived_at = datetime.now(UTC)

        # ARCHIVED 恢复
        if from_status == "ARCHIVED" and target_status == "previous_status":
            if not is_admin_or_lead:
                raise AppError(
                    code="FORBIDDEN", message="只有管理员有权限恢复已归档任务", status_code=403
                )
            if not reason_text or not reason_text.strip():
                raise AppError(
                    code="TEST_TASK_RESTORE_REASON_REQUIRED",
                    message="恢复归档的任务必须填写原因",
                    status_code=400,
                )

            target_status = task.previous_status or "DRAFT"
            task.previous_status = None
            task.archived_at = None

        # 检查目标状态合法性
        valid_statuses = [
            "DRAFT",
            "READY",
            "IN_PROGRESS",
            "BLOCKED",
            "COMPLETED",
            "CANCELLED",
            "ARCHIVED",
        ]
        if target_status not in valid_statuses:
            raise AppError(
                code="TEST_TASK_INVALID_TRANSITION",
                message=f"非法的目标任务状态: {target_status}",
                status_code=400,
            )

        # 执行转移
        task.status = target_status
        task.row_version += 1
        task.updated_by = uuid.UUID(str(actor_id))

        # 记录状态变动历史
        history = TestTaskStatusHistory(
            project_id=uuid.UUID(str(project_id)),
            task_id=task.id,
            from_status=from_status,
            to_status=target_status,
            reason_code=reason_code,
            reason_text=reason_text.strip() if reason_text else None,
            actor_id=uuid.UUID(str(actor_id)),
            request_id=request_id,
        )
        db.add(history)
        db.flush()

        AuditService.log_event(
            db,
            action="test_task.status_changed",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"流转测试任务 '{task.title}' 状态: 从 {from_status} 到 {target_status}",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

        return task
