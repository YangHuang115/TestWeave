from datetime import UTC, datetime
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityVersion,
    AICapabilityRun,
    AIArtifactSetRevision,
    AITestDesignRecord,
    CandidateSubmission,
    ProjectMember,
    Requirement,
    TestTask,
    TestTaskBlockage,
    TestTaskParticipant,
    TestTaskRequirement,
    UserRecentVisit,
    Version,
    VersionRequirement,
    TestCase,
)
from testweave.modules.workbench.schemas import (
    WorkbenchAgentRunItem,
    WorkbenchInProgressTask,
    WorkbenchRecentVisit,
    WorkbenchRemainingRequirement,
    WorkbenchSummary,
    WorkbenchTodoItem,
)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class WorkbenchService:
    @staticmethod
    def _is_remaining_requirement(db: Session, req: Requirement) -> bool:
        """判定 Requirement 是否为剩余需求

        口径：
        - status 排除 CANCELLED, ARCHIVED；
        - 查询所有关联 TestTask：
          - 若无关联任务 -> 计入剩余；
          - 若包含非终态任务 (DRAFT, READY, IN_PROGRESS, BLOCKED) -> 计入剩余；
          - 若包含 completed 任务，且没有新的非终态任务 -> 不计入剩余；
          - 若全为 cancelled/archived 任务且无 completed -> 计入剩余。
        """
        if req.status in ("CANCELLED", "ARCHIVED"):
            return False

        stmt = (
            select(TestTask)
            .join(TestTaskRequirement, TestTaskRequirement.task_id == TestTask.id)
            .where(TestTaskRequirement.requirement_id == req.id)
        )
        tasks = db.scalars(stmt).all()

        if not tasks:
            return True

        has_active = any(
            t.status in ("DRAFT", "READY", "IN_PROGRESS", "BLOCKED") for t in tasks
        )
        has_completed = any(t.status == "COMPLETED" for t in tasks)

        if has_completed and not has_active:
            return False

        return True

    @staticmethod
    def get_remaining_requirements(
        db: Session, project_id: str, user_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[WorkbenchRemainingRequirement], int]:
        """获取当前用户在项目中的剩余需求列表及总数"""
        stmt = (
            select(Requirement)
            .where(
                Requirement.project_id == uuid.UUID(project_id),
                Requirement.owner_id == uuid.UUID(user_id),
                Requirement.status.notin_(["CANCELLED", "ARCHIVED"]),
            )
            .order_by(Requirement.updated_at.desc())
        )
        all_reqs = db.scalars(stmt).all()

        remaining_reqs = [
            req for req in all_reqs if WorkbenchService._is_remaining_requirement(db, req)
        ]
        total = len(remaining_reqs)

        paged_reqs = remaining_reqs[offset : offset + limit]

        # 联表获取版本名称
        res: list[WorkbenchRemainingRequirement] = []
        for req in paged_reqs:
            version_stmt = (
                select(Version.name)
                .join(VersionRequirement, VersionRequirement.version_id == Version.id)
                .where(
                    VersionRequirement.requirement_id == req.id,
                    VersionRequirement.removed_at.is_(None),
                )
                .limit(1)
            )
            version_name = db.scalar(version_stmt)

            res.append(
                WorkbenchRemainingRequirement(
                    id=req.id,
                    requirement_no=req.requirement_no,
                    title=req.title,
                    priority=req.priority,
                    status=req.status,
                    version_name=version_name,
                    updated_at=req.updated_at,
                    target_route=f"/projects/{project_id}/requirements/{req.id}",
                )
            )

        return res, total

    @staticmethod
    def get_in_progress_tasks(
        db: Session, project_id: str, user_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[WorkbenchInProgressTask], int]:
        """获取当前用户负责人或参与人的进行中任务列表"""
        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)

        # 查 owner 任务
        owner_stmt = select(TestTask).where(
            TestTask.project_id == proj_uuid,
            TestTask.owner_id == user_uuid,
            TestTask.status == "IN_PROGRESS",
        )
        owner_tasks = db.scalars(owner_stmt).all()

        # 查 participant 任务
        participant_stmt = (
            select(TestTask)
            .join(TestTaskParticipant, TestTaskParticipant.task_id == TestTask.id)
            .where(
                TestTask.project_id == proj_uuid,
                TestTaskParticipant.user_id == user_uuid,
                TestTask.status == "IN_PROGRESS",
            )
        )
        participant_tasks = db.scalars(participant_stmt).all()

        # 按 Task ID 去重，owner 角色优先
        task_map: dict[uuid.UUID, tuple[TestTask, str]] = {}
        for t in owner_tasks:
            task_map[t.id] = (t, "OWNER")
        for t in participant_tasks:
            if t.id not in task_map:
                task_map[t.id] = (t, "PARTICIPANT")

        sorted_items = sorted(
            task_map.values(), key=lambda x: x[0].updated_at, reverse=True
        )
        total = len(sorted_items)
        paged_items = sorted_items[offset : offset + limit]

        res: list[WorkbenchInProgressTask] = []
        for task, role in paged_items:
            # 获取版本名称
            version_stmt = select(Version.name).where(Version.id == task.version_id)
            version_name = db.scalar(version_stmt) if task.version_id else None

            # 检查是否有未解除阻塞
            block_stmt = select(TestTaskBlockage).where(
                TestTaskBlockage.task_id == task.id,
                TestTaskBlockage.resolved_at.is_(None),
            )
            is_blocked = db.scalar(block_stmt) is not None or task.status == "BLOCKED"

            res.append(
                WorkbenchInProgressTask(
                    id=task.id,
                    task_no=task.task_no,
                    title=task.title,
                    version_id=task.version_id,
                    version_name=version_name,
                    role=role,
                    status=task.status,
                    progress_percent=None,
                    is_blocked=is_blocked,
                    updated_at=task.updated_at,
                )
            )

        return res, total

    @staticmethod
    def get_agent_runs(
        db: Session,
        project_id: str,
        user_id: str,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkbenchAgentRunItem], int]:
        """获取当前用户发起/相关的 Agent Runs"""
        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)

        conditions = [
            AICapabilityRun.project_id == proj_uuid,
            AICapabilityRun.initiator_id == user_uuid,
        ]

        if status_filter:
            conditions.append(AICapabilityRun.status == status_filter)

        count_stmt = select(func.count()).select_from(AICapabilityRun).where(*conditions)
        total = db.scalar(count_stmt) or 0

        stmt = (
            select(AICapabilityRun)
            .where(*conditions)
            .order_by(AICapabilityRun.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = db.scalars(stmt).all()

        res: list[WorkbenchAgentRunItem] = []
        for run in runs:
            # 查 AITestDesignRecord 获取关联 task_id
            design_rec = db.scalar(
                select(AITestDesignRecord).where(AITestDesignRecord.run_id == run.id)
            )
            task_id = design_rec.task_id if design_rec else None

            task_title = None
            if task_id:
                task_stmt = select(TestTask.title).where(TestTask.id == task_id)
                task_title = db.scalar(task_stmt)

            # 查 Capability Name
            cap_stmt = (
                select(AICapability.name, AICapability.id)
                .join(AICapabilityVersion, AICapabilityVersion.capability_id == AICapability.id)
                .where(AICapabilityVersion.id == run.capability_version_id)
            )
            cap_row = db.execute(cap_stmt).first()
            capability_name = cap_row[0] if cap_row else None
            capability_id = cap_row[1] if cap_row else None

            actions = []
            if run.status == "WAITING_HUMAN":
                actions = ["CONFIRM", "REJECT"]
            elif run.status in ("FAILED", "WAITING_RETRY"):
                actions = ["RETRY"]
            elif run.status in ("PENDING", "RUNNING"):
                actions = ["CANCEL"]

            res.append(
                WorkbenchAgentRunItem(
                    id=run.id,
                    capability_id=capability_id,
                    capability_name=capability_name,
                    task_id=task_id,
                    task_title=task_title,
                    status=run.status,
                    current_stage=getattr(run, "current_stage", None),
                    started_at=run.started_at,
                    updated_at=run.updated_at,
                    error_summary=run.error_summary,
                    executable_actions=actions,
                )
            )

        return res, total

    @staticmethod
    def get_todos(
        db: Session,
        project_id: str,
        user_id: str,
        type_filter: str | None = None,
        priority_filter: str | None = None,
        is_overdue_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkbenchTodoItem], int]:
        """聚合当前用户的多源待办，执行稳定排序与可选筛选"""
        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)
        now = datetime.now(UTC)

        raw_todos: list[WorkbenchTodoItem] = []

        # 来源 1：待设计需求
        req_items, _ = WorkbenchService.get_remaining_requirements(
            db, project_id, user_id, limit=200, offset=0
        )
        for req in req_items:
            if req.status in ("DRAFT", "READY"):
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"REQUIREMENT:{req.id}",
                        type="REQUIREMENT_DESIGN",
                        title=f"需求需进行测试设计: {req.requirement_no} {req.title}",
                        version_name=req.version_name,
                        priority=req.priority,
                        due_at=None,
                        created_at=req.updated_at,
                        urgency="NORMAL",
                        sub_item_count=1,
                        target_type="REQUIREMENT",
                        target_id=str(req.id),
                        target_route=req.target_route,
                    )
                )

        # 来源 2 & 3：待开始 / 阻塞 / 逾期任务
        task_stmt = (
            select(TestTask)
            .where(
                TestTask.project_id == proj_uuid,
                or_(
                    TestTask.owner_id == user_uuid,
                    TestTask.id.in_(
                        select(TestTaskParticipant.task_id).where(
                            TestTaskParticipant.user_id == user_uuid
                        )
                    ),
                ),
                TestTask.status.in_(["DRAFT", "READY", "IN_PROGRESS", "BLOCKED"]),
            )
        )
        tasks = db.scalars(task_stmt).all()

        for task in tasks:
            version_stmt = select(Version.name).where(Version.id == task.version_id)
            version_name = db.scalar(version_stmt) if task.version_id else None

            planned_end = _ensure_utc(task.planned_end_at)
            is_overdue = planned_end is not None and planned_end < now
            block_stmt = select(TestTaskBlockage).where(
                TestTaskBlockage.task_id == task.id,
                TestTaskBlockage.resolved_at.is_(None),
            )
            has_blockage = db.scalar(block_stmt) is not None or task.status == "BLOCKED"

            if has_blockage:
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"TASK_BLOCKED:{task.id}",
                        type="TASK_BLOCKED",
                        title=f"任务阻塞待处理: TASK-{task.task_no} {task.title}",
                        version_id=task.version_id,
                        version_name=version_name,
                        task_id=task.id,
                        task_title=task.title,
                        priority=task.priority if task.priority in ("HIGH", "MEDIUM", "LOW") else "HIGH",
                        due_at=task.planned_end_at,
                        created_at=task.created_at,
                        urgency="BLOCKED",
                        sub_item_count=1,
                        target_type="TASK",
                        target_id=str(task.id),
                        target_route=f"/projects/{project_id}/tasks/{task.id}",
                    )
                )
            elif is_overdue:
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"TASK_OVERDUE:{task.id}",
                        type="TASK_OVERDUE",
                        title=f"任务已逾期: TASK-{task.task_no} {task.title}",
                        version_id=task.version_id,
                        version_name=version_name,
                        task_id=task.id,
                        task_title=task.title,
                        priority=task.priority if task.priority in ("HIGH", "MEDIUM", "LOW") else "HIGH",
                        due_at=task.planned_end_at,
                        created_at=task.created_at,
                        urgency="OVERDUE",
                        sub_item_count=1,
                        target_type="TASK",
                        target_id=str(task.id),
                        target_route=f"/projects/{project_id}/tasks/{task.id}",
                    )
                )
            elif task.status in ("DRAFT", "READY") and task.owner_id == user_uuid:
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"TASK_START:{task.id}",
                        type="TASK_PENDING_START",
                        title=f"任务待开始: TASK-{task.task_no} {task.title}",
                        version_id=task.version_id,
                        version_name=version_name,
                        task_id=task.id,
                        task_title=task.title,
                        priority=task.priority if task.priority in ("HIGH", "MEDIUM", "LOW") else "MEDIUM",
                        due_at=task.planned_end_at,
                        created_at=task.created_at,
                        urgency="NORMAL",
                        sub_item_count=1,
                        target_type="TASK",
                        target_id=str(task.id),
                        target_route=f"/projects/{project_id}/tasks/{task.id}",
                    )
                )

        # 来源 4 & 5：AI Run WAITING_HUMAN / FAILED_RETRY
        run_stmt = select(AICapabilityRun).where(
            AICapabilityRun.project_id == proj_uuid,
            AICapabilityRun.initiator_id == user_uuid,
            AICapabilityRun.status.in_(["WAITING_HUMAN", "FAILED"]),
        )
        runs = db.scalars(run_stmt).all()

        for run in runs:
            design_rec = db.scalar(
                select(AITestDesignRecord).where(AITestDesignRecord.run_id == run.id)
            )
            task_id = design_rec.task_id if design_rec else None

            task_title = None
            if task_id:
                task_title = db.scalar(select(TestTask.title).where(TestTask.id == task_id))

            if run.status == "WAITING_HUMAN":
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"RUN_WAITING:{run.id}",
                        type="AI_WAITING_HUMAN",
                        title=f"AI 运行等待人工确认 (Run: {str(run.id)[:8]})",
                        task_id=task_id,
                        task_title=task_title,
                        priority="HIGH",
                        due_at=None,
                        created_at=run.updated_at,
                        urgency="BLOCKED",
                        sub_item_count=1,
                        target_type="AI_RUN",
                        target_id=str(run.id),
                        target_route=f"/projects/{project_id}/ai-test-design?runId={run.id}",
                    )
                )
            elif run.status == "FAILED":
                raw_todos.append(
                    WorkbenchTodoItem(
                        id=f"RUN_FAILED:{run.id}",
                        type="AI_FAILED_RETRY",
                        title=f"AI 运行失败待重试 (Run: {str(run.id)[:8]})",
                        task_id=task_id,
                        task_title=task_title,
                        priority="MEDIUM",
                        due_at=None,
                        created_at=run.updated_at,
                        urgency="NORMAL",
                        sub_item_count=1,
                        target_type="AI_RUN",
                        target_id=str(run.id),
                        target_route=f"/projects/{project_id}/ai-test-design?runId={run.id}",
                    )
                )

        # 来源 6：候选用例 / 测试点审核项（聚合）
        candidate_count_stmt = select(func.count()).select_from(CandidateSubmission).where(
            CandidateSubmission.project_id == proj_uuid,
            CandidateSubmission.submitted_by_user_id == user_uuid,
            CandidateSubmission.status == "SUBMITTED",
        )
        candidate_count = db.scalar(candidate_count_stmt) or 0

        if candidate_count > 0:
            raw_todos.append(
                WorkbenchTodoItem(
                    id=f"CANDIDATE_REVIEW:{proj_uuid}",
                    type="CANDIDATE_REVIEW",
                    title=f"待审核候选用例/测试点提交 ({candidate_count} 项)",
                    priority="HIGH",
                    due_at=None,
                    created_at=now,
                    urgency="NORMAL",
                    sub_item_count=candidate_count,
                    target_type="AI_TEST_DESIGN",
                    target_id=str(proj_uuid),
                    target_route=f"/projects/{project_id}/ai-test-design",
                )
            )

        # 过滤条件筛选
        filtered_todos = raw_todos
        if type_filter:
            filtered_todos = [t for t in filtered_todos if t.type == type_filter]
        if priority_filter:
            filtered_todos = [t for t in filtered_todos if t.priority == priority_filter]
        if is_overdue_only:
            filtered_todos = [
                t
                for t in filtered_todos
                if t.urgency == "OVERDUE"
                or (t.due_at and _ensure_utc(t.due_at) < now)
            ]

        # 待办排序函数
        def todo_sort_key(item: WorkbenchTodoItem):
            # 1. Urgency: BLOCKED(3) > OVERDUE(2) > NORMAL(1)
            urgency_rank = 3 if item.urgency == "BLOCKED" else (2 if item.urgency == "OVERDUE" else 1)
            # 2. Priority: HIGH(3) > MEDIUM(2) > LOW(1)
            priority_rank = 3 if item.priority == "HIGH" else (2 if item.priority == "MEDIUM" else 1)
            # 3. Due Date: 存在时间排前面，较小时间优先；无时间的排在最后
            due_ts = item.due_at.timestamp() if item.due_at else float("inf")
            # 4. Created Date: 产生时间倒序
            created_ts = -item.created_at.timestamp() if item.created_at else 0

            return (-urgency_rank, -priority_rank, due_ts, created_ts, item.id)

        sorted_todos = sorted(filtered_todos, key=todo_sort_key)
        total = len(sorted_todos)
        paged_todos = sorted_todos[offset : offset + limit]

        return paged_todos, total

    @staticmethod
    def get_summary(db: Session, project_id: str, user_id: str) -> WorkbenchSummary:
        """获取工作台 4 项个人概要卡统计数据"""
        _, remaining_req_count = WorkbenchService.get_remaining_requirements(
            db, project_id, user_id, limit=1, offset=0
        )
        _, my_todos_count = WorkbenchService.get_todos(
            db, project_id, user_id, limit=1, offset=0
        )
        _, in_progress_tasks_count = WorkbenchService.get_in_progress_tasks(
            db, project_id, user_id, limit=1, offset=0
        )

        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)
        waiting_human_stmt = select(func.count()).select_from(AICapabilityRun).where(
            AICapabilityRun.project_id == proj_uuid,
            AICapabilityRun.initiator_id == user_uuid,
            AICapabilityRun.status == "WAITING_HUMAN",
        )
        waiting_human_count = db.scalar(waiting_human_stmt) or 0

        return WorkbenchSummary(
            remaining_requirements_count=remaining_req_count,
            my_todos_count=my_todos_count,
            in_progress_tasks_count=in_progress_tasks_count,
            waiting_human_count=waiting_human_count,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def record_recent_visit(
        db: Session, project_id: str, user_id: str, resource_type: str, resource_id: str
    ) -> UserRecentVisit:
        """记录或更新用户的最近访问"""
        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)
        now = datetime.now(UTC)

        stmt = select(UserRecentVisit).where(
            UserRecentVisit.user_id == user_uuid,
            UserRecentVisit.project_id == proj_uuid,
            UserRecentVisit.resource_type == resource_type,
            UserRecentVisit.resource_id == resource_id,
        )
        visit = db.scalar(stmt)

        if visit:
            visit.visited_at = now
        else:
            visit = UserRecentVisit(
                user_id=user_uuid,
                project_id=proj_uuid,
                resource_type=resource_type,
                resource_id=resource_id,
                visited_at=now,
            )
            db.add(visit)

        db.flush()
        return visit

    @staticmethod
    def get_recent_visits(
        db: Session, project_id: str, user_id: str, limit: int = 10, offset: int = 0
    ) -> tuple[list[WorkbenchRecentVisit], int]:
        """查询用户最近访问列表，并校验源对象存在性与对应标题/路由"""
        user_uuid = uuid.UUID(user_id)
        proj_uuid = uuid.UUID(project_id)

        stmt = (
            select(UserRecentVisit)
            .where(
                UserRecentVisit.user_id == user_uuid,
                UserRecentVisit.project_id == proj_uuid,
            )
            .order_by(UserRecentVisit.visited_at.desc())
        )
        all_visits = db.scalars(stmt).all()

        res: list[WorkbenchRecentVisit] = []
        for visit in all_visits:
            title = None
            target_route = ""

            if visit.resource_type == "requirement":
                try:
                    req_uuid = uuid.UUID(visit.resource_id)
                    req = db.scalar(
                        select(Requirement).where(
                            Requirement.id == req_uuid, Requirement.project_id == proj_uuid
                        )
                    )
                    if req:
                        title = f"{req.requirement_no} {req.title}"
                        target_route = f"/projects/{project_id}/requirements/{req.id}"
                except ValueError:
                    pass
            elif visit.resource_type == "test_task":
                try:
                    task_uuid = uuid.UUID(visit.resource_id)
                    task = db.scalar(
                        select(TestTask).where(
                            TestTask.id == task_uuid, TestTask.project_id == proj_uuid
                        )
                    )
                    if task:
                        title = f"TASK-{task.task_no} {task.title}"
                        target_route = f"/projects/{project_id}/tasks/{task.id}"
                except ValueError:
                    pass
            elif visit.resource_type == "version":
                try:
                    ver_uuid = uuid.UUID(visit.resource_id)
                    ver = db.scalar(
                        select(Version).where(
                            Version.id == ver_uuid, Version.project_id == proj_uuid
                        )
                    )
                    if ver:
                        title = f"版本 {ver.name}"
                        target_route = f"/projects/{project_id}/versions/{ver.id}"
                except ValueError:
                    pass
            elif visit.resource_type == "test_case":
                try:
                    case_uuid = uuid.UUID(visit.resource_id)
                    case = db.scalar(
                        select(TestCase).where(
                            TestCase.id == case_uuid, TestCase.project_id == proj_uuid
                        )
                    )
                    if case:
                        title = f"{case.case_no} {case.title}"
                        target_route = f"/projects/{project_id}/test-cases/{case.id}"
                except ValueError:
                    pass

            # 源对象仍存在时保留
            if title and target_route:
                res.append(
                    WorkbenchRecentVisit(
                        id=visit.id,
                        resource_type=visit.resource_type,
                        resource_id=visit.resource_id,
                        title=title,
                        visited_at=visit.visited_at,
                        target_route=target_route,
                    )
                )

        total = len(res)
        paged_res = res[offset : offset + limit]
        return paged_res, total
