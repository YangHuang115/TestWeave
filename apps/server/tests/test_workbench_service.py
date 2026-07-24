import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityRun,
    AICapabilityVersion,
    Project,
    ProjectMember,
    Requirement,
    TestTask,
    TestTaskRequirement,
    User,
    Version,
)
from testweave.modules.workbench.service import WorkbenchService


@pytest.fixture
def workbench_data(db: Session):
    now = datetime.now(UTC)

    # 创建 2 个用户
    user_a = User(
        id=uuid.uuid4(),
        username="user_a",
        email="usera@test.com",
        display_name="User A",
        hashed_password="hash",
    )
    user_b = User(
        id=uuid.uuid4(),
        username="user_b",
        email="userb@test.com",
        display_name="User B",
        hashed_password="hash",
    )
    db.add_all([user_a, user_b])
    db.flush()

    # 创建 2 个项目
    proj_1 = Project(
        id=uuid.uuid4(),
        name="Project 1",
        key="P1",
        owner_id=user_a.id,
    )
    proj_2 = Project(
        id=uuid.uuid4(),
        name="Project 2",
        key="P2",
        owner_id=user_b.id,
    )
    db.add_all([proj_1, proj_2])
    db.flush()

    # 创建 Version
    ver_1 = Version(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        key="v1.0",
        key_normalized="v1.0",
        name="v1.0 Demo",
        owner_id=user_a.id,
        created_by=user_a.id,
    )
    db.add(ver_1)
    db.flush()

    # 创建 AICapability 与 Version
    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        namespace="system",
        code="test_design",
        name="Test Design",
        category="TEST_DESIGN",
        scope="PROJECT",
        status="ACTIVE",
    )
    db.add(cap)
    db.flush()

    cap_ver = AICapabilityVersion(
        id=uuid.uuid4(),
        capability_id=cap.id,
        version="1.0.0",
        status="PUBLISHED",
        package_fingerprint="hash123",
        created_by=user_a.id,
    )
    db.add(cap_ver)
    db.flush()

    # 添加项目成员
    db.add_all(
        [
            ProjectMember(project_id=proj_1.id, user_id=user_a.id, role_id="project_admin"),
            ProjectMember(project_id=proj_1.id, user_id=user_b.id, role_id="test_member"),
            ProjectMember(project_id=proj_2.id, user_id=user_b.id, role_id="project_admin"),
        ]
    )
    db.flush()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "proj_1": proj_1,
        "proj_2": proj_2,
        "ver_1": ver_1,
        "cap_ver": cap_ver,
        "now": now,
    }


def test_remaining_requirements_formula(db: Session, workbench_data):
    user_a = workbench_data["user_a"]
    proj_1 = workbench_data["proj_1"]
    ver_1 = workbench_data["ver_1"]
    now = workbench_data["now"]

    # 1. 需求没有任何任务 -> 计入剩余
    req_no_task = Requirement(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        requirement_no="REQ-101",
        requirement_no_normalized="req-101",
        title="No task req",
        priority="HIGH",
        status="DRAFT",
        owner_id=user_a.id,
    )
    db.add(req_no_task)

    # 2. 需求关联已完成任务 (COMPLETED) -> 不计入剩余
    req_completed = Requirement(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        requirement_no="REQ-102",
        requirement_no_normalized="req-102",
        title="Completed task req",
        priority="MEDIUM",
        status="READY",
        owner_id=user_a.id,
    )
    db.add(req_completed)
    db.flush()

    task_completed = TestTask(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        version_id=ver_1.id,
        task_no="1",
        task_type="CASE_DESIGN",
        title="Completed task",
        status="COMPLETED",
        owner_id=user_a.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=1),
        created_by=user_a.id,
    )
    db.add(task_completed)
    db.flush()
    db.add(TestTaskRequirement(task_id=task_completed.id, requirement_id=req_completed.id))

    # 3. 需求同时关联 COMPLETED 和 新的 IN_PROGRESS 任务 -> 仍计入剩余
    req_new_active = Requirement(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        requirement_no="REQ-103",
        requirement_no_normalized="req-103",
        title="Completed and in progress req",
        priority="HIGH",
        status="READY",
        owner_id=user_a.id,
    )
    db.add(req_new_active)
    db.flush()

    task_active = TestTask(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        version_id=ver_1.id,
        task_no="2",
        task_type="CASE_DESIGN",
        title="Active task",
        status="IN_PROGRESS",
        owner_id=user_a.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=1),
        created_by=user_a.id,
    )
    db.add(task_active)
    db.flush()
    db.add(TestTaskRequirement(task_id=task_active.id, requirement_id=req_new_active.id))
    db.commit()

    # 验证 get_remaining_requirements
    reqs, total = WorkbenchService.get_remaining_requirements(
        db, str(proj_1.id), str(user_a.id)
    )
    req_ids = [r.id for r in reqs]

    assert total == 2
    assert req_no_task.id in req_ids
    assert req_new_active.id in req_ids
    assert req_completed.id not in req_ids


def test_todo_sorting_and_user_isolation(db: Session, workbench_data):
    user_a = workbench_data["user_a"]
    user_b = workbench_data["user_b"]
    proj_1 = workbench_data["proj_1"]
    ver_1 = workbench_data["ver_1"]
    now = workbench_data["now"]

    # 给 user_a 创建 1 个普通待办需求
    req = Requirement(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        requirement_no="REQ-201",
        requirement_no_normalized="req-201",
        title="Normal Todo Req",
        priority="MEDIUM",
        status="DRAFT",
        owner_id=user_a.id,
    )
    db.add(req)

    # 给 user_a 创建 1 个 WAITING_HUMAN Run (最高优先级，BLOCKED)
    run_blocked = AICapabilityRun(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        capability_version_id=workbench_data["cap_ver"].id,
        initiator_id=user_a.id,
        trace_id=f"trace-{uuid.uuid4()}",
        input_snapshot={},
        execution_snapshot={},
        status="WAITING_HUMAN",
        created_at=now,
        updated_at=now,
    )
    db.add(run_blocked)

    # 给 user_a 创建 1 个逾期任务 (OVERDUE)
    task_overdue = TestTask(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        version_id=ver_1.id,
        task_no="10",
        task_type="CASE_DESIGN",
        title="Overdue task",
        status="IN_PROGRESS",
        owner_id=user_a.id,
        planned_start_at=now - timedelta(days=2),
        planned_end_at=now - timedelta(days=1),
        created_by=user_a.id,
    )
    db.add(task_overdue)

    # 给 user_b 创建 1 个待办项（不应混入 user_a 列表）
    req_b = Requirement(
        id=uuid.uuid4(),
        project_id=proj_1.id,
        requirement_no="REQ-202",
        requirement_no_normalized="req-202",
        title="User B Req",
        priority="HIGH",
        status="DRAFT",
        owner_id=user_b.id,
    )
    db.add(req_b)
    db.commit()

    # 查 user_a 待办
    todos, total = WorkbenchService.get_todos(db, str(proj_1.id), str(user_a.id))

    assert total == 3
    # 验证排序：BLOCKED (WAITING_HUMAN) -> OVERDUE -> NORMAL (Requirement)
    assert todos[0].type == "AI_WAITING_HUMAN"
    assert todos[1].type == "TASK_OVERDUE"
    assert todos[2].type == "REQUIREMENT_DESIGN"
