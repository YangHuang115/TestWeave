"""M06 测试执行：服务层不变量单元测试（SQLite）。

覆盖 START-HERE 五条关键规则：
1. 创建执行任务时原子冻结全部范围与用例快照（幂等、不再与用例库同步）。
2. 执行用例行创建后范围与快照不可变。
3. 每次执行新增一条历史记录，禁止覆盖（追加式）。
4. 不做轮次/用例级执行人分配（资格仅按 owner/participant/admin_or_lead）。
5. 所有用例至少执行一次后才能完成任务。
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    ExecutionCase,
    ExecutionRecord,
    TestCase,
    TestCaseRevision,
)
from testweave.modules.cases.service import TestCaseService
from testweave.modules.executions.service import (
    ExecutionRecordService,
    ExecutionTaskService,
)
from testweave.modules.executions.xlsx_export import build_xlsx
from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.test_tasks.service import TestTaskService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService


@pytest.fixture
def execution_test_context(db: Session) -> dict:
    user = UserService.create_user(
        db,
        username="exectester",
        email="ex@testweave.com",
        display_name="Exec Tester",
        password="test-password",
    )
    db.commit()

    project = ProjectService.create_project(
        db, key="EXECPROJ", name="Exec Project", owner_id=user.id, request_id="r-p"
    )
    db.commit()

    now = datetime.now(UTC)
    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1",
        owner_id=user.id,
        planned_start_at=now - timedelta(days=1),
        planned_end_at=now + timedelta(days=30),
        actor_id=user.id,
        request_id="r-v",
    )
    db.commit()

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-E1",
        title="登录功能",
        description="",
        priority="HIGH",
        owner_id=user.id,
        actor_id=user.id,
        request_id="r-r",
    )
    RequirementService.associate_to_version(
        db,
        project_id=project.id,
        requirement_id=req.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="r-rv",
    )
    db.commit()

    design = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="设计任务",
        description="",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=10),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="r-d",
        requirement_id=req.id,
    )
    db.commit()

    return {
        "user": user,
        "project": project,
        "version": version,
        "requirement": req,
        "design": design,
    }


def _add_case(db: Session, ctx: dict, idx: int) -> TestCase:
    case = TestCaseService.create_case(
        db,
        project_id=ctx["project"].id,
        title=f"用例{idx}",
        precondition=None,
        priority="MEDIUM",
        case_type="FUNCTIONAL",
        tags_json=[],
        test_data_note=None,
        note=None,
        steps=[{"action": f"步骤{idx}", "expected_result": "ok"}],
        source_task_id=ctx["design"].id,
        actor_id=ctx["user"].id,
        request_id=f"r-c{idx}",
    )
    db.commit()
    return case


def _create_exec_task(db: Session, ctx: dict, key: str) -> object:
    now = datetime.now(UTC)
    return ExecutionTaskService.create_execution_task(
        db=db,
        project_id=str(ctx["project"].id),
        source_design_task_id=str(ctx["design"].id),
        title="执行任务",
        description=None,
        priority="MEDIUM",
        owner_id=str(ctx["user"].id),
        participant_ids=None,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=5),
        test_environment={"name": "staging"},
        build_version="1.0.0",
        test_goal=None,
        tags_json=None,
        idempotency_key=key,
        actor_id=str(ctx["user"].id),
        request_id="r-exec",
    )


def _transition(db: Session, ctx: dict, task: object, target: str) -> object:
    t = ExecutionTaskService.get_execution_task(db, str(ctx["project"].id), str(task.id))
    return TestTaskService.transition_status(
        db,
        project_id=str(ctx["project"].id),
        task_id=str(task.id),
        target_status=target,
        reason_code=None,
        reason_text=None,
        expected_row_version=t.row_version,
        actor_id=str(ctx["user"].id),
        request_id="r-trans",
        is_admin_or_lead=True,
    )


def _exec_case(db: Session, task: object, source_case_id: object) -> ExecutionCase:
    ec = db.scalar(
        select(ExecutionCase).where(
            ExecutionCase.test_case_id == source_case_id,
            ExecutionCase.execution_task_id == task.id,
        )
    )
    assert ec is not None
    return ec


def _record(
    db: Session,
    ctx: dict,
    task: object,
    source_case_id: object,
    result: str,
    *,
    actual: str | None = None,
    idem: str = "k",
    admin: bool = True,
) -> ExecutionRecord:
    ec = _exec_case(db, task, source_case_id)
    return ExecutionRecordService.create_record(
        db=db,
        project_id=str(ctx["project"].id),
        task_id=str(task.id),
        execution_case_id=str(ec.id),
        result=result,
        actual_result=actual,
        note=None,
        reason_code=None,
        reason_text=None,
        evidences=None,
        idempotency_key=idem,
        actor_id=str(ctx["user"].id),
        request_id="r-rec",
        is_admin_or_lead=admin,
    )


def test_create_execution_task_freezes_scope_and_idempotent(
    db: Session, execution_test_context: dict
) -> None:
    ctx = execution_test_context
    _add_case(db, ctx, 1)
    _add_case(db, ctx, 2)

    task = _create_exec_task(db, ctx, "idem-1")
    db.commit()

    assert task.task_type == "TEST_EXECUTION"
    assert task.status == "DRAFT"

    profile = ExecutionTaskService.get_profile(db, str(task.id))
    assert profile.total_count == 2
    assert profile.not_run_count == 2
    assert profile.passed_count == 0

    case_rows = db.scalars(
        select(ExecutionCase).where(ExecutionCase.execution_task_id == task.id)
    ).all()
    assert len(case_rows) == 2

    # 幂等：相同 project + 来源 + 键 返回首次创建的任务
    task_again = _create_exec_task(db, ctx, "idem-1")
    assert task_again.id == task.id
    # 不同键则再冻结一份（按设计，键维度幂等而非来源维度唯一）
    task_b = _create_exec_task(db, ctx, "idem-2")
    assert task_b.id != task.id


def test_execution_case_snapshot_immutable(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    case = _add_case(db, ctx, 1)
    _create_exec_task(db, ctx, "idem-imm")
    db.commit()

    ec = db.scalar(select(ExecutionCase).where(ExecutionCase.test_case_id == case.id))
    assert ec is not None
    original_title = ec.case_snapshot["title"]

    # 修改来源用例的修订快照
    revision = db.get(TestCaseRevision, case.current_revision_id)
    assert revision is not None
    revision.snapshot = dict(revision.snapshot)
    revision.snapshot["title"] = "HACKED"
    db.flush()

    # 执行用例行的冻结快照不受影响
    ec2 = db.get(ExecutionCase, ec.id)
    assert ec2.case_snapshot["title"] == original_title


def test_source_task_must_have_cases(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    with pytest.raises(AppError) as exc:
        _create_exec_task(db, ctx, "no-cases")
    assert exc.value.code == "EXECUTION_SOURCE_TASK_HAS_NO_CASES"


def test_resolve_stable_requires_case_design(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    _add_case(db, ctx, 1)
    # 直接对一个执行任务再建执行任务应被拒绝（来源必须是 CASE_DESIGN）
    exec_task = _create_exec_task(db, ctx, "first")
    db.commit()
    with pytest.raises(AppError) as exc:
        ExecutionTaskService.create_execution_task(
            db=db,
            project_id=str(ctx["project"].id),
            source_design_task_id=str(exec_task.id),
            title="再次执行",
            description=None,
            priority="MEDIUM",
            owner_id=str(ctx["user"].id),
            participant_ids=None,
            planned_start_at=datetime.now(UTC),
            planned_end_at=datetime.now(UTC) + timedelta(days=5),
            test_environment=None,
            build_version=None,
            test_goal=None,
            tags_json=None,
            idempotency_key="x",
            actor_id=str(ctx["user"].id),
            request_id="r",
        )
    assert exc.value.code == "EXECUTION_SOURCE_TASK_INVALID"


def test_record_flow_and_completion_guard(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    c2 = _add_case(db, ctx, 2)
    c3 = _add_case(db, ctx, 3)
    task = _create_exec_task(db, ctx, "idem-flow")
    db.commit()

    _transition(db, ctx, task, "READY")

    # 记录其中两条
    _record(db, ctx, task, c1.id, "PASSED", idem="r1")
    _record(db, ctx, task, c2.id, "PASSED", idem="r2")
    db.commit()

    preview = ExecutionRecordService.completion_preview(db, str(ctx["project"].id), str(task.id))
    assert preview["notRun"] == 1
    assert preview["passed"] == 2

    # 仍有未执行用例，完成应被拒绝
    with pytest.raises(AppError) as exc:
        ExecutionRecordService.complete(
            db,
            str(ctx["project"].id),
            str(task.id),
            str(ctx["user"].id),
            "r-complete",
            is_admin_or_lead=True,
        )
    assert exc.value.code == "EXECUTION_COMPLETION_NOT_RUN_EXISTS"

    # 记录最后一条后完成
    _record(db, ctx, task, c3.id, "PASSED", idem="r3")
    db.commit()
    updated = ExecutionRecordService.complete(
        db,
        str(ctx["project"].id),
        str(task.id),
        str(ctx["user"].id),
        "r-complete",
        is_admin_or_lead=True,
    )
    db.commit()
    assert updated.status == "COMPLETED"

    profile = ExecutionTaskService.get_profile(db, str(task.id))
    assert profile.not_run_count == 0
    assert profile.passed_count == 3


def test_failed_requires_actual_result(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    task = _create_exec_task(db, ctx, "idem-fail")
    db.commit()
    _transition(db, ctx, task, "READY")

    with pytest.raises(AppError) as exc:
        _record(db, ctx, task, c1.id, "FAILED", idem="bad")
    assert exc.value.code == "EXECUTION_FAILED_ACTUAL_RESULT_REQUIRED"

    rec = _record(db, ctx, task, c1.id, "FAILED", actual="实际报错信息", idem="good")
    db.commit()
    assert rec.result == "FAILED"
    ec = db.get(ExecutionCase, rec.execution_case_id)
    assert ec.current_result == "FAILED"
    assert ec.latest_actual_result == "实际报错信息"


def test_append_only_records(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    task = _create_exec_task(db, ctx, "idem-append")
    db.commit()
    _transition(db, ctx, task, "READY")

    _record(db, ctx, task, c1.id, "PASSED", idem="a1")
    _record(db, ctx, task, c1.id, "FAILED", actual="x", idem="a2")
    db.commit()

    rows, total = ExecutionRecordService.list_records(
        db, str(ctx["project"].id), str(task.id), str(_exec_case(db, task, c1.id).id), 100, 0
    )
    assert total == 2
    assert [r.record_no for r in rows] == [1, 2]
    # 当前结果反映最新一条
    ec = _exec_case(db, task, c1.id)
    assert ec.current_result == "FAILED"
    assert ec.execution_count == 2


def test_record_on_draft_blocked(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    task = _create_exec_task(db, ctx, "idem-draft")
    db.commit()
    # 未流转到 READY/IN_PROGRESS
    with pytest.raises(AppError) as exc:
        _record(db, ctx, task, c1.id, "PASSED", idem="d1")
    assert exc.value.code == "EXECUTION_TASK_NOT_READY"


def test_batch_pass(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    c2 = _add_case(db, ctx, 2)
    c3 = _add_case(db, ctx, 3)
    task = _create_exec_task(db, ctx, "idem-batch")
    db.commit()
    _transition(db, ctx, task, "READY")

    ec_ids = [str(_exec_case(db, task, c.id).id) for c in (c1, c2, c3)]
    res = ExecutionRecordService.batch_pass(
        db,
        str(ctx["project"].id),
        str(task.id),
        ec_ids,
        "bp-key",
        str(ctx["user"].id),
        "r-bp",
        is_admin_or_lead=True,
    )
    db.commit()
    assert res["total"] == 3
    assert res["succeeded"] == 3
    assert res["failed"] == 0

    for c in (c1, c2, c3):
        ec = _exec_case(db, task, c.id)
        assert ec.current_result == "PASSED"


def test_reopen_requires_admin_or_lead(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    c2 = _add_case(db, ctx, 2)
    task = _create_exec_task(db, ctx, "idem-reopen")
    db.commit()
    _transition(db, ctx, task, "READY")
    _record(db, ctx, task, c1.id, "PASSED", idem="p1")
    _record(db, ctx, task, c2.id, "PASSED", idem="p2")
    db.commit()
    ExecutionRecordService.complete(
        db,
        str(ctx["project"].id),
        str(task.id),
        str(ctx["user"].id),
        "r-c",
        is_admin_or_lead=True,
    )
    db.commit()

    # 非管理员/负责人被拒绝
    with pytest.raises(AppError) as exc:
        ExecutionRecordService.reopen(
            db,
            str(ctx["project"].id),
            str(task.id),
            "需要补充测试",
            str(ctx["user"].id),
            "r-ro",
            is_admin_or_lead=False,
        )
    assert exc.value.code == "EXECUTION_PERMISSION_DENIED"

    # 管理员可重开
    reopened = ExecutionRecordService.reopen(
        db,
        str(ctx["project"].id),
        str(task.id),
        "需要补充测试",
        str(ctx["user"].id),
        "r-ro",
        is_admin_or_lead=True,
    )
    db.commit()
    assert reopened.status == "IN_PROGRESS"


def test_record_idempotent_same_key(db: Session, execution_test_context: dict) -> None:
    ctx = execution_test_context
    c1 = _add_case(db, ctx, 1)
    task = _create_exec_task(db, ctx, "idem-rec")
    db.commit()
    _transition(db, ctx, task, "READY")

    r1 = _record(db, ctx, task, c1.id, "PASSED", idem="same")
    r2 = _record(db, ctx, task, c1.id, "PASSED", idem="same")
    db.commit()
    assert r1.id == r2.id  # 相同用户+键返回原记录
    rows, total = ExecutionRecordService.list_records(
        db, str(ctx["project"].id), str(task.id), str(_exec_case(db, task, c1.id).id), 100, 0
    )
    assert rows[0].record_no == 1
    assert total == 1  # 不重复写入


def test_xlsx_formula_injection_escaped() -> None:
    sheets = [
        {
            "name": "结果",
            "rows": [
                ["=cmd", "+plus", "-minus", "@at", "normal", 5, 3.14, True],
            ],
        }
    ]
    data = build_xlsx(sheets)
    assert data[:2] == b"PK"  # zip 文件头
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    # 危险前缀被前置单引号转义
    assert "'=cmd" in xml
    assert "'+plus" in xml
    assert "'-minus" in xml
    assert "'@at" in xml
    # 普通文本与数值不受影响
    assert ">normal<" in xml
    assert "<v>5</v>" in xml
    assert "<v>3.14</v>" in xml
