import re
import unicodedata
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapabilityRun,
    AITestDesignRecord,
    Project,
    Requirement,
    TestTask,
    TestTaskParticipant,
    TestTaskRequirement,
    Version,
)

TASK_KEY_PATTERN = re.compile(
    r"(?<![A-Z0-9-])TASK-[A-Z0-9][A-Z0-9-]*(?![A-Z0-9-])",
    re.IGNORECASE,
)
REQUIREMENT_KEY_PATTERN = re.compile(
    r"(?<![A-Z0-9-])REQ-\d+(?![A-Z0-9-])",
    re.IGNORECASE,
)
GENERIC_CONTINUE_PATTERN = re.compile(
    r"^(?:"
    r"(?:继续|接着)(?:(?:上次(?:的)?|当前)(?:工作|任务)|(?:做|处理|生成)?"
    r"(?:需求分析|测试点|脑图|测试用例|用例生成|用例评审))?"
    r"|(?:打开|查看|返回|回到)(?:我的|当前|上次)?工作台"
    r"|(?:做|处理|生成)?(?:需求分析|测试点|脑图|测试用例|用例生成|用例评审)"
    r"|continue|resume|openworkbench|myworkbench"
    r")$",
)
CONTENT_NOISE_PHRASES = (
    "测试用例评审",
    "requirementanalysis",
    "casegeneration",
    "用例评审",
    "用例生成",
    "用例设计",
    "测试用例",
    "需求分析",
    "需求梳理",
    "testpoint",
    "casereview",
    "测试点",
    "工作台",
    "继续",
    "接着",
    "处理",
    "生成",
    "设计",
    "相关",
    "当前",
    "上次",
    "打开",
    "查看",
    "返回",
    "回到",
    "任务",
    "工作",
    "脑图",
    "用例",
    "测试",
    "的",
    "做",
    "为",
)

STAGE_INTENTS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("用例评审", "测试用例评审", "用例审核", "case review"),
        "case-review",
        "test_case_review_report@1.0",
    ),
    (("测试点", "脑图", "test point"), "test-points", "test_point_set@1.0"),
    (("测试用例", "用例生成", "case generation"), "test-cases", "test_case_set@1.0"),
    (
        ("需求分析", "需求梳理", "requirement analysis"),
        "requirement-analysis",
        "requirement_analysis@1.0",
    ),
)
ARTIFACT_TYPE_BY_STAGE = {
    "requirement-analysis": "requirement_analysis@1.0",
    "test-points": "test_point_set@1.0",
    "test-cases": "test_case_set@1.0",
    "case-review": "test_case_review_report@1.0",
}

TASK_BLOCKERS: dict[str, tuple[str, str]] = {
    "BLOCKED": ("TASK_BLOCKED", "测试任务当前处于 BLOCKED 状态，需要先解除阻塞"),
    "CANCELLED": ("TASK_CANCELLED", "测试任务已取消，不能直接继续执行"),
    "ARCHIVED": ("TASK_ARCHIVED", "测试任务已归档，不能直接继续执行"),
    "COMPLETED": ("TASK_COMPLETED", "测试任务已完成，需要先重新打开后再继续执行"),
}


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _compact_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", _normalize_text(value), flags=re.UNICODE)


def _bigrams(value: str) -> set[str]:
    compact = _compact_text(value)
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def _content_text(value: str) -> str:
    compact = _compact_text(value)
    for phrase in CONTENT_NOISE_PHRASES:
        compact = compact.replace(phrase, "")
    return compact


class WorkbenchHandshakeService:
    """解析首句并返回无状态、只读、可直接执行的 Gateway 工作台快照。"""

    @classmethod
    def resolve(
        cls,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        message: str,
    ) -> dict[str, Any]:
        project = db.get(Project, project_id)
        if project is None:
            raise AppError(
                code="PROJECT_NOT_FOUND",
                message="项目不存在或无权限访问",
                status_code=404,
            )

        intent = cls._resolve_intent(message)
        tasks = list(
            db.scalars(
                select(TestTask)
                .where(TestTask.project_id == project_id)
                .order_by(TestTask.updated_at.desc(), TestTask.id.asc())
            ).all()
        )
        requirements_by_task, tasks_by_requirement = cls._load_requirement_links(db, project_id)

        base_response = {
            "readOnly": True,
            "intent": {
                "message": message.strip(),
                "stage": intent["stage"],
                "artifactType": intent["artifactType"],
            },
            "project": {
                "id": str(project.id),
                "key": project.key,
                "name": project.name,
            },
            "workbench": None,
            "entryPoint": None,
            "candidates": [],
            "blockers": [],
        }

        task_keys = {key.upper() for key in TASK_KEY_PATTERN.findall(message)}
        if task_keys:
            matched_tasks = [task for task in tasks if task.task_no.upper() in task_keys]
            if not matched_tasks:
                return {"status": "NOT_FOUND", **base_response}
            matched_task_keys = {task.task_no.upper() for task in matched_tasks}
            unresolved_task_keys = sorted(task_keys - matched_task_keys)
            if len(task_keys) > 1:
                return {
                    "status": "NEEDS_SELECTION",
                    **base_response,
                    "candidates": [cls._build_candidate(task) for task in matched_tasks],
                    "blockers": (
                        [
                            {
                                "code": "UNRESOLVED_TASK_KEYS",
                                "message": (
                                    "部分任务编号未找到：" + "、".join(unresolved_task_keys)
                                ),
                            }
                        ]
                        if unresolved_task_keys
                        else []
                    ),
                }
            return cls._build_task_response(
                db=db,
                base_response=base_response,
                task=matched_tasks[0],
                requirements=requirements_by_task.get(matched_tasks[0].id, []),
                intent=intent,
            )

        requirement_keys = {key.upper() for key in REQUIREMENT_KEY_PATTERN.findall(message)}
        if requirement_keys:
            requirements = list(
                db.scalars(
                    select(Requirement).where(
                        Requirement.project_id == project_id,
                        Requirement.requirement_no.in_(requirement_keys),
                    )
                ).all()
            )
            if not requirements:
                return {"status": "NOT_FOUND", **base_response}
            matched_requirement_keys = {
                requirement.requirement_no.upper() for requirement in requirements
            }
            unresolved_requirement_keys = sorted(requirement_keys - matched_requirement_keys)
            if len(requirement_keys) > 1:
                return {
                    "status": "NEEDS_SELECTION",
                    **base_response,
                    "candidates": [
                        cls._build_requirement_candidate(requirement)
                        for requirement in requirements
                    ],
                    "blockers": (
                        [
                            {
                                "code": "UNRESOLVED_REQUIREMENT_KEYS",
                                "message": (
                                    "部分需求编号未找到：" + "、".join(unresolved_requirement_keys)
                                ),
                            }
                        ]
                        if unresolved_requirement_keys
                        else []
                    ),
                }

            requirement = requirements[0]
            linked_tasks = tasks_by_requirement.get(requirement.id, [])
            requirement_workbench = {"requirement": cls._build_requirement(requirement)}
            if not linked_tasks:
                return {
                    "status": "BLOCKED",
                    **base_response,
                    "workbench": requirement_workbench,
                    "blockers": [
                        {
                            "code": "REQUIREMENT_HAS_NO_TASK",
                            "message": "需求尚未关联测试任务，不能直接进入测试设计执行",
                        }
                    ],
                }
            case_design_tasks = [task for task in linked_tasks if task.task_type == "CASE_DESIGN"]
            if not case_design_tasks:
                return {
                    "status": "BLOCKED",
                    **base_response,
                    "workbench": requirement_workbench,
                    "blockers": [
                        {
                            "code": "REQUIREMENT_HAS_NO_CASE_DESIGN_TASK",
                            "message": "需求未关联可用于 AI 测试设计的用例设计任务",
                        }
                    ],
                }
            if len(case_design_tasks) > 1:
                return {
                    "status": "NEEDS_SELECTION",
                    **base_response,
                    "workbench": requirement_workbench,
                    "candidates": [cls._build_candidate(task) for task in case_design_tasks],
                }
            return cls._build_task_response(
                db=db,
                base_response=base_response,
                task=case_design_tasks[0],
                requirements=requirements_by_task.get(case_design_tasks[0].id, []),
                intent=intent,
            )

        matched_tasks = cls._match_tasks_by_content(
            message=message,
            tasks=tasks,
            requirements_by_task=requirements_by_task,
        )
        if len(matched_tasks) > 1:
            return {
                "status": "NEEDS_SELECTION",
                **base_response,
                "candidates": [cls._build_candidate(task) for task in matched_tasks],
            }
        if len(matched_tasks) == 1:
            task = matched_tasks[0]
            return cls._build_task_response(
                db=db,
                base_response=base_response,
                task=task,
                requirements=requirements_by_task.get(task.id, []),
                intent=intent,
            )

        if not cls._is_generic_continue_message(message):
            return {"status": "NOT_FOUND", **base_response}

        participant_task_ids = set(
            db.scalars(
                select(TestTaskParticipant.task_id).where(TestTaskParticipant.user_id == user_id)
            ).all()
        )
        fallback_task = cls._select_recent_user_task(
            tasks,
            user_id,
            participant_task_ids,
        )
        if fallback_task is None:
            return {"status": "NOT_FOUND", **base_response}
        return cls._build_task_response(
            db=db,
            base_response=base_response,
            task=fallback_task,
            requirements=requirements_by_task.get(fallback_task.id, []),
            intent=intent,
        )

    @staticmethod
    def _resolve_intent(message: str) -> dict[str, Any]:
        normalized = _normalize_text(message)
        for keywords, stage, artifact_type in STAGE_INTENTS:
            if any(keyword in normalized for keyword in keywords):
                return {
                    "stage": stage,
                    "artifactType": artifact_type,
                    "explicit": True,
                }
        return {
            "stage": "requirement-analysis",
            "artifactType": "requirement_analysis@1.0",
            "explicit": False,
        }

    @staticmethod
    def _is_generic_continue_message(message: str) -> bool:
        return GENERIC_CONTINUE_PATTERN.fullmatch(_compact_text(message)) is not None

    @staticmethod
    def _load_requirement_links(
        db: Session, project_id: uuid.UUID
    ) -> tuple[
        dict[uuid.UUID, list[Requirement]],
        dict[uuid.UUID, list[TestTask]],
    ]:
        rows = db.execute(
            select(TestTaskRequirement, Requirement, TestTask)
            .join(
                Requirement,
                Requirement.id == TestTaskRequirement.requirement_id,
            )
            .join(TestTask, TestTask.id == TestTaskRequirement.task_id)
            .where(
                Requirement.project_id == project_id,
                TestTask.project_id == project_id,
            )
            .order_by(TestTask.updated_at.desc(), TestTask.id.asc())
        ).all()

        requirements_by_task: dict[uuid.UUID, list[Requirement]] = defaultdict(list)
        tasks_by_requirement: dict[uuid.UUID, list[TestTask]] = defaultdict(list)
        for _link, requirement, task in rows:
            requirements_by_task[task.id].append(requirement)
            tasks_by_requirement[requirement.id].append(task)
        return dict(requirements_by_task), dict(tasks_by_requirement)

    @classmethod
    def _match_tasks_by_content(
        cls,
        *,
        message: str,
        tasks: list[TestTask],
        requirements_by_task: dict[uuid.UUID, list[Requirement]],
    ) -> list[TestTask]:
        normalized_message = _content_text(message)
        if not normalized_message:
            return []
        message_bigrams = _bigrams(normalized_message)
        scored: list[tuple[float, TestTask]] = []
        for task in tasks:
            if task.task_type != "CASE_DESIGN":
                continue
            texts = [task.title, task.description or ""]
            texts.extend(requirement.title for requirement in requirements_by_task.get(task.id, []))
            score = max(
                cls._content_score(
                    normalized_message=normalized_message,
                    message_bigrams=message_bigrams,
                    candidate=text,
                )
                for text in texts
                if text
            )
            if score >= 0.35:
                scored.append((score, task))

        if not scored:
            return []
        scored.sort(key=lambda item: (-item[0], -item[1].updated_at.timestamp()))
        top_score = scored[0][0]
        return [task for score, task in scored if top_score - score <= 0.1]

    @staticmethod
    def _content_score(
        *,
        normalized_message: str,
        message_bigrams: set[str],
        candidate: str,
    ) -> float:
        normalized_candidate = _content_text(candidate)
        if not normalized_candidate:
            return 0.0
        if normalized_candidate in normalized_message or normalized_message in normalized_candidate:
            return 1.0
        candidate_bigrams = _bigrams(normalized_candidate)
        if not candidate_bigrams:
            return 0.0
        return len(message_bigrams & candidate_bigrams) / len(candidate_bigrams)

    @staticmethod
    def _select_recent_user_task(
        tasks: list[TestTask],
        user_id: uuid.UUID,
        participant_task_ids: set[uuid.UUID],
    ) -> TestTask | None:
        active_statuses = {"DRAFT", "READY", "IN_PROGRESS", "BLOCKED"}
        user_tasks = [
            task
            for task in tasks
            if task.task_type == "CASE_DESIGN"
            and (task.owner_id == user_id or task.id in participant_task_ids)
            and task.status in active_statuses
        ]
        return user_tasks[0] if user_tasks else None

    @classmethod
    def _build_task_response(
        cls,
        *,
        db: Session,
        base_response: dict[str, Any],
        task: TestTask,
        requirements: list[Requirement],
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[dict[str, str]] = []
        task_blocker = TASK_BLOCKERS.get(task.status)
        if task_blocker:
            blockers.append({"code": task_blocker[0], "message": task_blocker[1]})
        if task.task_type != "CASE_DESIGN":
            blockers.append(
                {
                    "code": "UNSUPPORTED_TASK_TYPE",
                    "message": "只有用例设计任务可以进入 AI 测试设计流程",
                }
            )
        elif len(requirements) != 1:
            blockers.append(
                {
                    "code": "TASK_REQUIREMENT_REQUIRED",
                    "message": "AI 测试设计要求任务恰好关联一个需求",
                }
            )

        ai_design = cls._load_ai_design_state(db, task)
        resolved_intent = dict(intent)
        if ai_design is not None and not intent.get("explicit"):
            last_opened_stage = ai_design.get("lastOpenedStage")
            if isinstance(last_opened_stage, str):
                artifact_type = ARTIFACT_TYPE_BY_STAGE.get(last_opened_stage)
                if artifact_type is not None:
                    resolved_intent["stage"] = last_opened_stage
                    resolved_intent["artifactType"] = artifact_type

        resolved_base_response = {
            **base_response,
            "intent": {
                **base_response["intent"],
                "stage": resolved_intent["stage"],
                "artifactType": resolved_intent["artifactType"],
            },
        }
        if ai_design is not None and ai_design.get("runStatus") == "WAITING_HUMAN":
            blockers.append(
                {
                    "code": "WAITING_HUMAN",
                    "message": "当前 AI 测试设计记录正在等待人工确认",
                }
            )

        workbench = {
            "version": cls._build_version(db, task.version_id),
            "task": cls._build_task(task),
            "requirements": [cls._build_requirement(requirement) for requirement in requirements],
            "aiDesign": ai_design,
        }
        if blockers:
            return {
                "status": "BLOCKED",
                **resolved_base_response,
                "workbench": workbench,
                "blockers": blockers,
            }

        entry_point = {
            "action": "LOAD_TASK_CONTEXT",
            "method": "GET",
            "path": f"/external/v1/tasks/{task.id}",
            "taskId": str(task.id),
            "taskKey": task.task_no,
            "stage": resolved_intent["stage"],
            "artifactType": resolved_intent["artifactType"],
        }
        return {
            "status": "READY",
            **resolved_base_response,
            "workbench": workbench,
            "entryPoint": entry_point,
        }

    @staticmethod
    def _load_ai_design_state(db: Session, task: TestTask) -> dict[str, Any] | None:
        record = db.scalar(
            select(AITestDesignRecord)
            .where(
                AITestDesignRecord.project_id == task.project_id,
                AITestDesignRecord.task_id == task.id,
            )
            .order_by(
                AITestDesignRecord.updated_at.desc(),
                AITestDesignRecord.record_no.desc(),
            )
            .limit(1)
        )
        if record is None:
            return None
        run = db.get(AICapabilityRun, record.run_id)
        return {
            "recordId": str(record.id),
            "recordNo": record.record_no,
            "title": record.title,
            "lastOpenedStage": record.last_opened_stage,
            "runId": str(record.run_id),
            "runStatus": run.status if run is not None else None,
            "updatedAt": record.updated_at.isoformat(),
        }

    @staticmethod
    def _build_version(db: Session, version_id: uuid.UUID) -> dict[str, Any] | None:
        version = db.get(Version, version_id)
        if version is None:
            return None
        return {
            "id": str(version.id),
            "key": version.key,
            "name": version.name,
            "status": version.status,
        }

    @staticmethod
    def _build_task(task: TestTask) -> dict[str, Any]:
        return {
            "id": str(task.id),
            "key": task.task_no,
            "title": task.title,
            "status": task.status,
            "taskType": task.task_type,
            "priority": task.priority,
            "updatedAt": task.updated_at.isoformat(),
        }

    @staticmethod
    def _build_requirement(requirement: Requirement) -> dict[str, Any]:
        return {
            "id": str(requirement.id),
            "key": requirement.requirement_no,
            "title": requirement.title,
            "status": requirement.status,
            "priority": requirement.priority,
        }

    @staticmethod
    def _build_candidate(task: TestTask) -> dict[str, Any]:
        return {
            "type": "TASK",
            "id": str(task.id),
            "key": task.task_no,
            "title": task.title,
            "status": task.status,
        }

    @staticmethod
    def _build_requirement_candidate(
        requirement: Requirement,
    ) -> dict[str, Any]:
        return {
            "type": "REQUIREMENT",
            "id": str(requirement.id),
            "key": requirement.requirement_no,
            "title": requirement.title,
            "status": requirement.status,
        }
