"""M06 测试执行核心服务。

关键不变量（详见 docs/features/M06-test-execution）：
- 创建执行任务时原子冻结全部有效用例、稳定修订与正文快照；
- 创建后不与 M05 同步、不增删范围、不替换修订、不编辑正文；
- 每次执行新增一条不可覆盖的 ExecutionRecord（append-only）；
- executedBy / executedAt 由服务端生成；
- 所有用例至少执行一次后才能完成任务；
- 完成后必须重新打开才能继续新增执行记录；
- 支持图片/文本日志/压缩日志/HTTPS 外链证据；
- M07 接入前不创建临时缺陷表。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    ExecutionCase,
    ExecutionRecord,
    ExecutionTaskProfile,
    ProjectMember,
    TestTask,
    TestTaskParticipant,
    TestTaskRequirement,
    Version,
)
from testweave.modules.audit.service import AuditService
from testweave.modules.cases.service import TestCaseService
from testweave.modules.executions import evidence as evidence_service
from testweave.modules.test_tasks.service import TestTaskService

RESULT_VALUES = {"PASSED", "FAILED", "BLOCKED", "SKIPPED"}
COMPLETION_RESULTS = RESULT_VALUES  # 这些均视为“已执行”


def utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_snapshot(snapshot: dict[str, Any]) -> str:
    serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _result_count_attr(result: str) -> str:
    return {
        "PASSED": "passed_count",
        "FAILED": "failed_count",
        "BLOCKED": "blocked_count",
        "SKIPPED": "skipped_count",
    }[result]


class ExecutionTaskService:
    @staticmethod
    def get_execution_task(db: Session, project_id: str, task_id: str) -> TestTask:
        task = TestTaskService.get_task_by_id(db, project_id, task_id)
        if task.task_type != "TEST_EXECUTION":
            raise AppError(
                code="EXECUTION_TASK_TYPE_INVALID",
                message="该任务不是用例执行任务",
                status_code=400,
            )
        return task

    @staticmethod
    def get_profile(db: Session, execution_task_id: str) -> ExecutionTaskProfile:
        profile = db.get(ExecutionTaskProfile, uuid.UUID(str(execution_task_id)))
        if profile is None:
            raise AppError(
                code="EXECUTION_PROFILE_MISSING",
                message="执行任务配置不存在",
                status_code=404,
            )
        return profile

    @staticmethod
    def create_execution_task(
        db: Session,
        project_id: str,
        source_design_task_id: str,
        title: str,
        description: str | None,
        priority: str,
        owner_id: str,
        participant_ids: list[str] | None,
        planned_start_at: datetime | None,
        planned_end_at: datetime,
        test_environment: dict[str, Any] | None,
        build_version: str | None,
        test_goal: str | None,
        tags_json: list[str] | None,
        idempotency_key: str,
        actor_id: str,
        request_id: str,
    ) -> TestTask:
        """原子创建用例执行任务，并一次性冻结完整执行范围。失败整体回滚。"""
        proj_uuid = uuid.UUID(str(project_id))
        actor_uuid = uuid.UUID(str(actor_id))

        # 1. 创建幂等：相同项目/来源/键重复返回首次结果
        dup_profile = db.scalar(
            select(ExecutionTaskProfile).where(
                ExecutionTaskProfile.project_id == proj_uuid,
                ExecutionTaskProfile.source_design_task_id == uuid.UUID(str(source_design_task_id)),
                ExecutionTaskProfile.create_idempotency_key == idempotency_key,
            )
        )
        if dup_profile is not None:
            existing = db.get(TestTask, dup_profile.execution_task_id)
            if existing is not None:
                return existing

        # 2. 来源设计任务校验
        source_task = TestTaskService.get_task_by_id(db, project_id, source_design_task_id)
        if source_task.task_type != "CASE_DESIGN":
            raise AppError(
                code="EXECUTION_SOURCE_TASK_INVALID",
                message="来源任务必须是用例设计任务（CASE_DESIGN）",
                status_code=400,
            )
        if source_task.archived_at is not None:
            raise AppError(
                code="EXECUTION_SOURCE_TASK_INVALID",
                message="来源用例设计任务已归档，无法创建执行任务",
                status_code=400,
            )

        # 唯一需求校验
        req_links = db.scalars(
            select(TestTaskRequirement).where(TestTaskRequirement.task_id == source_task.id)
        ).all()
        if len(req_links) != 1:
            raise AppError(
                code="EXECUTION_SOURCE_TASK_REQUIREMENT_INVALID",
                message="来源用例设计任务必须且只能关联一个有效需求",
                status_code=400,
            )
        requirement_id = req_links[0].requirement_id

        # 版本与时间校验
        version = db.get(Version, source_task.version_id)
        if version is None:
            raise AppError(code="VERSION_NOT_FOUND", message="所属版本不存在", status_code=404)
        start_at = planned_start_at if planned_start_at else utc_now()
        TestTaskService._validate_times(db, start_at, planned_end_at, version)
        TestTaskService._validate_owner(db, project_id, owner_id)

        # 参与人校验
        participant_uuids: list[uuid.UUID] = []
        if participant_ids:
            filtered = [
                uuid.UUID(str(pid)) for pid in participant_ids if uuid.UUID(str(pid)) != actor_uuid
            ]
            unique = list({str(u) for u in filtered})
            if unique:
                member_stmt = select(ProjectMember).where(
                    ProjectMember.project_id == proj_uuid,
                    ProjectMember.user_id.in_([uuid.UUID(u) for u in unique]),
                )
                valid = db.scalars(member_stmt).all()
                if len(valid) != len(unique):
                    raise AppError(
                        code="TEST_TASK_PARTICIPANT_INVALID",
                        message="部分参与人不是该项目的有效成员",
                        status_code=400,
                    )
                participant_uuids = [uuid.UUID(u) for u in unique]

        # 3. M05 稳定修订解析（可能 finalize OPEN 编辑会话）
        resolved = TestCaseService.resolve_stable_revisions_for_source_task(
            db, project_id, source_design_task_id, actor_id
        )
        for r in resolved:
            r["snapshot"]["sourceRequirementId"] = str(requirement_id)

        # 4. 创建 TEST_EXECUTION 任务（DRAFT）
        task_no = TestTaskService.generate_next_task_no(db, project_id)
        task = TestTask(
            project_id=proj_uuid,
            version_id=source_task.version_id,
            task_no=task_no,
            task_type="TEST_EXECUTION",
            status="DRAFT",
            title=title.strip(),
            description=description,
            priority=priority,
            owner_id=uuid.UUID(str(owner_id)),
            planned_start_at=start_at,
            planned_end_at=planned_end_at,
            test_goal=test_goal,
            tags_json=tags_json,
            row_version=1,
            created_by=actor_uuid,
        )
        db.add(task)
        db.flush()

        # 写入参与人（供执行资格判定）
        for pu in participant_uuids:
            db.add(TestTaskParticipant(task_id=task.id, user_id=pu, added_by=actor_uuid))
        db.flush()

        # 5. 执行任务配置与统计
        total = len(resolved)
        profile = ExecutionTaskProfile(
            execution_task_id=task.id,
            project_id=proj_uuid,
            source_design_task_id=uuid.UUID(str(source_design_task_id)),
            source_requirement_id=requirement_id,
            create_idempotency_key=idempotency_key,
            test_environment=test_environment,
            build_version=build_version,
            scope_frozen_at=utc_now(),
            total_count=total,
            not_run_count=total,
            passed_count=0,
            failed_count=0,
            blocked_count=0,
            skipped_count=0,
            execution_record_count=0,
        )
        db.add(profile)
        db.flush()

        # 6. 批量创建执行用例行（冻结快照）
        for r in resolved:
            ec = ExecutionCase(
                project_id=proj_uuid,
                execution_task_id=task.id,
                test_case_id=uuid.UUID(str(r["test_case_id"])),
                test_case_revision_id=uuid.UUID(str(r["revision_id"])),
                case_snapshot=r["snapshot"],
                case_snapshot_hash=r["snapshot_hash"],
                execution_count=0,
                row_version=1,
                scope_created_at=utc_now(),
            )
            db.add(ec)
        db.flush()

        AuditService.log_event(
            db,
            action="test_execution.created",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"创建用例执行任务 '{task.title}' 并冻结 {total} 条用例",
            request_id=request_id,
            project_id=proj_uuid,
            actor_id=actor_uuid,
        )
        AuditService.log_event(
            db,
            action="test_execution.scope_frozen",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"建立并冻结执行范围，共 {total} 条用例",
            request_id=request_id,
            project_id=proj_uuid,
            actor_id=actor_uuid,
        )
        return task

    @staticmethod
    def list_execution_cases(
        db: Session,
        project_id: str,
        task_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ExecutionCase], int]:
        ExecutionTaskService.get_execution_task(db, project_id, task_id)
        total = (
            db.query(func.count(ExecutionCase.id))
            .where(ExecutionCase.execution_task_id == uuid.UUID(str(task_id)))
            .scalar()
            or 0
        )
        stmt = (
            select(ExecutionCase)
            .where(ExecutionCase.execution_task_id == uuid.UUID(str(task_id)))
            .order_by(ExecutionCase.scope_created_at.asc(), ExecutionCase.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = db.scalars(stmt).all()
        return list(rows), int(total)

    @staticmethod
    def recompute_statistics(db: Session, task_id: str) -> ExecutionTaskProfile:
        """从 execution_cases 重新计算冗余统计，用于校验/修复。"""
        profile = ExecutionTaskService.get_profile(db, task_id)
        rows = db.scalars(
            select(ExecutionCase).where(ExecutionCase.execution_task_id == uuid.UUID(str(task_id)))
        ).all()
        total = len(rows)
        profile.total_count = total
        profile.not_run_count = sum(1 for r in rows if r.current_result is None)
        profile.passed_count = sum(1 for r in rows if r.current_result == "PASSED")
        profile.failed_count = sum(1 for r in rows if r.current_result == "FAILED")
        profile.blocked_count = sum(1 for r in rows if r.current_result == "BLOCKED")
        profile.skipped_count = sum(1 for r in rows if r.current_result == "SKIPPED")
        profile.execution_record_count = sum(r.execution_count for r in rows)
        db.flush()
        return profile


class ExecutionRecordService:
    @staticmethod
    def _assert_eligible(
        db: Session, task: TestTask, actor_id: str, is_admin_or_lead: bool
    ) -> None:
        if is_admin_or_lead:
            return
        if task.owner_id == uuid.UUID(str(actor_id)):
            return
        part = db.scalar(
            select(TestTaskParticipant).where(
                TestTaskParticipant.task_id == task.id,
                TestTaskParticipant.user_id == uuid.UUID(str(actor_id)),
            )
        )
        if part is not None:
            return
        raise AppError(
            code="EXECUTION_PERMISSION_DENIED",
            message="只有任务负责人、参与人、测试负责人或项目管理员可以执行该任务内的用例",
            status_code=403,
        )

    @staticmethod
    def _apply_stat_delta(
        db: Session,
        profile: ExecutionTaskProfile,
        old_result: str | None,
        new_result: str,
    ) -> None:
        """根据旧/新结果更新冗余统计计数。"""
        if old_result is None:
            profile.not_run_count = max(0, profile.not_run_count - 1)
        elif old_result != new_result:
            old_attr = _result_count_attr(old_result)
            setattr(profile, old_attr, max(0, getattr(profile, old_attr) - 1))
        # 新结果计数（old == new 时净变化为 0，仅 record_count 增加）
        if old_result != new_result:
            new_attr = _result_count_attr(new_result)
            setattr(profile, new_attr, getattr(profile, new_attr) + 1)
        profile.execution_record_count += 1
        db.flush()

    @staticmethod
    def _bind_evidences(
        db: Session,
        project_id: str,
        task_id: str,
        record: ExecutionRecord,
        evidences: list[dict[str, Any]] | None,
        actor_id: str,
        request_id: str,
    ) -> None:
        if not evidences:
            return
        for ev in evidences:
            kind = ev.get("kind")
            if kind == "external_link":
                evidence_service.create_external_link_evidence(
                    db,
                    project_id,
                    task_id,
                    str(record.id),
                    str(ev.get("url", "")),
                    actor_id,
                    request_id,
                )
            elif kind == "file":
                evidence_service.create_file_evidence(
                    db,
                    project_id,
                    task_id,
                    str(record.id),
                    str(ev.get("evidenceType", "IMAGE")),
                    str(ev.get("objectKey", "")),
                    ev.get("fileName"),
                    ev.get("mimeType"),
                    ev.get("fileSize"),
                    ev.get("checksum"),
                    actor_id,
                    request_id,
                )
            # 未知证据类型忽略，不阻断主记录保存

    @staticmethod
    def create_record(
        db: Session,
        project_id: str,
        task_id: str,
        execution_case_id: str,
        result: str,
        actual_result: str | None,
        note: str | None,
        reason_code: str | None,
        reason_text: str | None,
        evidences: list[dict[str, Any]] | None,
        idempotency_key: str,
        actor_id: str,
        request_id: str,
        is_admin_or_lead: bool = False,
        record_source: str = "MANUAL",
        correction_of_record_id: str | None = None,
        correction_note: str | None = None,
    ) -> ExecutionRecord:
        task = ExecutionTaskService.get_execution_task(db, project_id, task_id)
        if task.status not in ("READY", "IN_PROGRESS"):
            if task.status == "DRAFT":
                raise AppError(
                    code="EXECUTION_TASK_NOT_READY",
                    message="执行任务尚未进入待开始状态，无法记录执行结果",
                    status_code=400,
                )
            raise AppError(
                code="EXECUTION_TASK_COMPLETED",
                message="执行任务已完成，必须重新打开后才能继续记录执行结果",
                status_code=400,
            )

        ExecutionRecordService._assert_eligible(db, task, actor_id, is_admin_or_lead)

        case = db.get(ExecutionCase, uuid.UUID(str(execution_case_id)))
        if case is None or case.execution_task_id != task.id:
            raise AppError(
                code="EXECUTION_CASE_NOT_FOUND",
                message="执行用例不存在或不属于当前执行任务",
                status_code=404,
            )

        # 幂等：同一用户+键重复提交返回原记录
        dup = db.scalar(
            select(ExecutionRecord).where(
                ExecutionRecord.execution_task_id == task.id,
                ExecutionRecord.executed_by == uuid.UUID(str(actor_id)),
                ExecutionRecord.idempotency_key == idempotency_key,
            )
        )
        if dup is not None:
            return dup

        if result not in RESULT_VALUES:
            raise AppError(
                code="EXECUTION_RESULT_INVALID",
                message="执行结果只能是 PASSED / FAILED / BLOCKED / SKIPPED",
                status_code=400,
            )
        if result == "FAILED" and not actual_result:
            raise AppError(
                code="EXECUTION_FAILED_ACTUAL_RESULT_REQUIRED",
                message="失败（FAILED）必须填写实际结果",
                status_code=400,
            )

        if correction_of_record_id:
            target = db.get(ExecutionRecord, uuid.UUID(str(correction_of_record_id)))
            if target is None or target.execution_case_id != case.id:
                raise AppError(
                    code="EXECUTION_CORRECTION_TARGET_INVALID",
                    message="纠正记录必须引用同一条执行用例的旧记录",
                    status_code=400,
                )
            if not correction_note:
                raise AppError(
                    code="EXECUTION_CORRECTION_NOTE_REQUIRED",
                    message="纠正记录必须填写纠正说明",
                    status_code=400,
                )

        executed_at = utc_now()
        new_no = case.execution_count + 1
        allow_reason = result in ("BLOCKED", "SKIPPED")
        record = ExecutionRecord(
            project_id=task.project_id,
            execution_task_id=task.id,
            execution_case_id=case.id,
            record_no=new_no,
            result=result,
            actual_result=actual_result,
            note=note,
            reason_code=reason_code if allow_reason else None,
            reason_text=reason_text if allow_reason else None,
            executed_by=uuid.UUID(str(actor_id)),
            executed_at=executed_at,
            build_snapshot=None,  # 下面从 profile 取
            environment_snapshot=None,
            record_source=record_source,
            correction_of_record_id=(
                uuid.UUID(str(correction_of_record_id)) if correction_of_record_id else None
            ),
            correction_note=correction_note,
            idempotency_key=idempotency_key,
        )
        # 任务级构建/环境快照
        profile = ExecutionTaskService.get_profile(db, task_id)
        record.build_snapshot = profile.build_version
        record.environment_snapshot = profile.test_environment
        db.add(record)
        db.flush()

        # 更新执行用例最新投影
        old_result = case.current_result
        case.current_result = result
        case.latest_record_id = record.id
        case.latest_actual_result = actual_result
        case.latest_note = note
        case.latest_executed_by = uuid.UUID(str(actor_id))
        case.latest_executed_at = executed_at
        case.execution_count = new_no
        case.row_version += 1
        db.flush()

        # 更新统计
        ExecutionRecordService._apply_stat_delta(db, profile, old_result, result)

        # 首条记录 READY -> IN_PROGRESS
        if task.status == "READY":
            TestTaskService.transition_status(
                db,
                project_id=project_id,
                task_id=task_id,
                target_status="IN_PROGRESS",
                reason_code=None,
                reason_text=None,
                expected_row_version=task.row_version,
                actor_id=actor_id,
                request_id=request_id,
                is_admin_or_lead=is_admin_or_lead,
            )

        # 证据绑定
        ExecutionRecordService._bind_evidences(
            db, project_id, task_id, record, evidences, actor_id, request_id
        )

        action = (
            "test_execution.record_corrected"
            if correction_of_record_id
            else "test_execution.record_created"
        )
        AuditService.log_event(
            db,
            action=action,
            object_type="ExecutionRecord",
            object_id=str(record.id),
            summary=f"记录执行结果 {result}（用例 {case.case_snapshot.get('caseNo', '')}）",
            request_id=request_id,
            project_id=task.project_id,
            actor_id=uuid.UUID(str(actor_id)),
        )
        return record

    @staticmethod
    def list_records(
        db: Session,
        project_id: str,
        task_id: str,
        execution_case_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ExecutionRecord], int]:
        ExecutionTaskService.get_execution_task(db, project_id, task_id)
        case = db.get(ExecutionCase, uuid.UUID(str(execution_case_id)))
        if case is None or case.execution_task_id != uuid.UUID(str(task_id)):
            raise AppError(
                code="EXECUTION_CASE_NOT_FOUND",
                message="执行用例不存在或不属于当前执行任务",
                status_code=404,
            )
        total = (
            db.query(func.count(ExecutionRecord.id))
            .where(ExecutionRecord.execution_case_id == case.id)
            .scalar()
            or 0
        )
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.execution_case_id == case.id)
            .order_by(ExecutionRecord.record_no.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = db.scalars(stmt).all()
        return list(rows), int(total)

    @staticmethod
    def completion_preview(db: Session, project_id: str, task_id: str) -> dict[str, Any]:
        ExecutionTaskService.get_execution_task(db, project_id, task_id)
        profile = ExecutionTaskService.get_profile(db, task_id)
        return {
            "total": profile.total_count,
            "notRun": profile.not_run_count,
            "passed": profile.passed_count,
            "failed": profile.failed_count,
            "blocked": profile.blocked_count,
            "skipped": profile.skipped_count,
            "failureWithoutDefect": profile.failed_count,  # M07 未接入，失败均视为无缺陷
        }

    @staticmethod
    def complete(
        db: Session,
        project_id: str,
        task_id: str,
        actor_id: str,
        request_id: str,
        is_admin_or_lead: bool,
    ) -> TestTask:
        task = ExecutionTaskService.get_execution_task(db, project_id, task_id)
        # 完成权限：负责人或测试负责人/项目管理员
        if not (task.owner_id == uuid.UUID(str(actor_id)) or is_admin_or_lead):
            raise AppError(
                code="EXECUTION_PERMISSION_DENIED",
                message="只有任务负责人、测试负责人或项目管理员可以完成执行任务",
                status_code=403,
            )
        # 再次校验无未执行用例
        profile = ExecutionTaskService.get_profile(db, task_id)
        if profile.not_run_count > 0:
            raise AppError(
                code="EXECUTION_COMPLETION_NOT_RUN_EXISTS",
                message="仍有未执行的用例，无法完成任务",
                status_code=400,
            )
        updated = TestTaskService.transition_status(
            db,
            project_id=project_id,
            task_id=task_id,
            target_status="COMPLETED",
            reason_code=None,
            reason_text=None,
            expected_row_version=task.row_version,
            actor_id=actor_id,
            request_id=request_id,
            is_admin_or_lead=is_admin_or_lead,
        )
        AuditService.log_event(
            db,
            action="test_execution.completed",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"完成任务 '{task.title}'",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
        return updated

    @staticmethod
    def reopen(
        db: Session,
        project_id: str,
        task_id: str,
        reason_text: str,
        actor_id: str,
        request_id: str,
        is_admin_or_lead: bool,
    ) -> TestTask:
        task = ExecutionTaskService.get_execution_task(db, project_id, task_id)
        if not is_admin_or_lead:
            raise AppError(
                code="EXECUTION_PERMISSION_DENIED",
                message="只有测试负责人或项目管理员可以重新打开已完成的执行任务",
                status_code=403,
            )
        if not reason_text or not reason_text.strip():
            raise AppError(
                code="EXECUTION_REOPEN_REASON_REQUIRED",
                message="重新打开已完成的任务必须填写原因",
                status_code=400,
            )
        updated = TestTaskService.transition_status(
            db,
            project_id=project_id,
            task_id=task_id,
            target_status="IN_PROGRESS",
            reason_code=None,
            reason_text=reason_text.strip(),
            expected_row_version=task.row_version,
            actor_id=actor_id,
            request_id=request_id,
            is_admin_or_lead=is_admin_or_lead,
        )
        AuditService.log_event(
            db,
            action="test_execution.reopened",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"重新打开任务 '{task.title}'",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
        return updated

    @staticmethod
    def batch_pass(
        db: Session,
        project_id: str,
        task_id: str,
        execution_case_ids: list[str],
        idempotency_key: str,
        actor_id: str,
        request_id: str,
        is_admin_or_lead: bool = False,
    ) -> dict[str, Any]:
        task = ExecutionTaskService.get_execution_task(db, project_id, task_id)
        if task.status not in ("READY", "IN_PROGRESS"):
            raise AppError(
                code="EXECUTION_TASK_NOT_READY",
                message="执行任务未处于可执行状态，无法批量通过",
                status_code=400,
            )
        ExecutionRecordService._assert_eligible(db, task, actor_id, is_admin_or_lead)

        items: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for case_id in execution_case_ids:
            try:
                rec = ExecutionRecordService.create_record(
                    db=db,
                    project_id=project_id,
                    task_id=task_id,
                    execution_case_id=case_id,
                    result="PASSED",
                    actual_result=None,
                    note=None,
                    reason_code=None,
                    reason_text=None,
                    evidences=None,
                    idempotency_key=f"{idempotency_key}::{case_id}",
                    actor_id=actor_id,
                    request_id=request_id,
                    is_admin_or_lead=is_admin_or_lead,
                    record_source="BATCH_PASS",
                )
                items.append(
                    {
                        "executionCaseId": case_id,
                        "status": "SUCCEEDED",
                        "recordId": str(rec.id),
                    }
                )
                succeeded += 1
            except AppError as e:
                items.append(
                    {
                        "executionCaseId": case_id,
                        "status": "FAILED",
                        "errorCode": e.code,
                        "message": e.message,
                    }
                )
                failed += 1

        AuditService.log_event(
            db,
            action="test_execution.batch_pass_completed",
            object_type="TestTask",
            object_id=str(task.id),
            summary=f"批量通过 {succeeded} 条，失败 {failed} 条",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
        return {
            "total": len(execution_case_ids),
            "succeeded": succeeded,
            "failed": failed,
            "items": items,
        }
