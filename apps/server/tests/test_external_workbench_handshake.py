import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from testweave.api.dependencies.database import get_db
from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import (
    AICapabilityRun,
    CandidateSubmission,
    Project,
    ProjectMember,
    Requirement,
    TestTask,
    TestTaskRequirement,
    User,
    Version,
)
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_test_design.service import AiTestDesignService


@pytest.fixture
def workbench_handshake_context(db: Session) -> dict[str, Any]:
    user = User(
        email=f"handshake_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"handshake_{uuid.uuid4().hex[:6]}",
        display_name="Gateway Handshake User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(user)
    db.flush()

    project = Project(
        name="Gateway 握手项目",
        key=f"GW_{uuid.uuid4().hex[:6]}".upper(),
        owner_id=user.id,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_id="project_admin",
        )
    )

    version = Version(
        project_id=project.id,
        key="0.0.1",
        key_normalized="0.0.1",
        name="0.0.1 demo版本",
        status="ACTIVE",
        owner_id=user.id,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    login_requirement = Requirement(
        project_id=project.id,
        requirement_no="REQ-21001",
        requirement_no_normalized="req-21001",
        title="用户登录与会话",
        description="用户登录后建立安全会话。",
        priority="HIGH",
        status="READY",
        owner_id=user.id,
    )
    payment_requirement = Requirement(
        project_id=project.id,
        requirement_no="REQ-21002",
        requirement_no_normalized="req-21002",
        title="订单支付",
        description="用户提交订单后完成支付。",
        priority="MEDIUM",
        status="READY",
        owner_id=user.id,
    )
    db.add_all([login_requirement, payment_requirement])
    db.flush()

    now = datetime.now(UTC)
    login_task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-LOGIN-001",
        task_type="CASE_DESIGN",
        status="IN_PROGRESS",
        title="用户登录用例设计",
        description="为用户登录需求设计测试点与测试用例。",
        priority="HIGH",
        owner_id=user.id,
        planned_start_at=now - timedelta(days=1),
        planned_end_at=now + timedelta(days=3),
        updated_at=now,
    )
    payment_task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-PAY-001",
        task_type="CASE_DESIGN",
        status="BLOCKED",
        title="订单支付用例设计",
        description="为订单支付需求设计测试点与测试用例。",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now - timedelta(days=1),
        planned_end_at=now + timedelta(days=3),
        updated_at=now - timedelta(hours=1),
    )
    secondary_login_task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-LOGIN-002",
        task_type="CASE_DESIGN",
        status="READY",
        title="登录安全专项设计",
        description="覆盖登录安全相关风险。",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=5),
        updated_at=now - timedelta(hours=2),
    )
    execution_task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-EXEC-001",
        task_type="TEST_EXECUTION",
        status="IN_PROGRESS",
        title="用户登录执行任务",
        description="执行用户登录回归测试。",
        priority="HIGH",
        owner_id=user.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=2),
        updated_at=now + timedelta(minutes=1),
    )
    unlinked_task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-NO-REQ-001",
        task_type="CASE_DESIGN",
        status="READY",
        title="未关联需求用例设计",
        description="尚未建立需求关联。",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=2),
        updated_at=now - timedelta(hours=3),
    )
    db.add_all(
        [
            login_task,
            payment_task,
            secondary_login_task,
            execution_task,
            unlinked_task,
        ]
    )
    db.flush()
    db.add_all(
        [
            TestTaskRequirement(
                task_id=login_task.id,
                requirement_id=login_requirement.id,
                linked_by=user.id,
            ),
            TestTaskRequirement(
                task_id=payment_task.id,
                requirement_id=payment_requirement.id,
                linked_by=user.id,
            ),
            TestTaskRequirement(
                task_id=secondary_login_task.id,
                requirement_id=login_requirement.id,
                linked_by=user.id,
            ),
            TestTaskRequirement(
                task_id=execution_task.id,
                requirement_id=login_requirement.id,
                linked_by=user.id,
            ),
        ]
    )

    other_user = User(
        email=f"other_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"other_{uuid.uuid4().hex[:6]}",
        display_name="Other Project User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(other_user)
    db.flush()
    other_project = Project(
        name="其他项目",
        key=f"OTHER_{uuid.uuid4().hex[:6]}".upper(),
        owner_id=other_user.id,
    )
    db.add(other_project)
    db.flush()
    other_version = Version(
        project_id=other_project.id,
        key="0.0.1",
        key_normalized="0.0.1",
        name="其他项目版本",
        status="ACTIVE",
        owner_id=other_user.id,
        created_by=other_user.id,
    )
    db.add(other_version)
    db.flush()
    db.add(
        TestTask(
            project_id=other_project.id,
            version_id=other_version.id,
            task_no="TASK-SECRET-001",
            task_type="CASE_DESIGN",
            status="IN_PROGRESS",
            title="不可泄露的其他项目任务",
            priority="HIGH",
            owner_id=other_user.id,
            planned_start_at=now,
            planned_end_at=now + timedelta(days=1),
        )
    )
    db.commit()

    return {
        "user": user,
        "project": project,
        "version": version,
        "login_requirement": login_requirement,
        "login_task": login_task,
        "payment_task": payment_task,
        "secondary_login_task": secondary_login_task,
        "execution_task": execution_task,
        "unlinked_task": unlinked_task,
    }


def _create_test_app(db: Session):
    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.anyio
async def test_first_message_resolves_task_and_returns_read_only_entry_point(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context["login_task"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Workbench Handshake Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read", "revision:candidate"],
    )
    submissions_before = db.scalar(select(func.count()).select_from(CandidateSubmission))

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续处理TASK-LOGIN-001的测试点生成"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["readOnly"] is True
    assert body["intent"]["stage"] == "test-points"
    assert body["intent"]["artifactType"] == "test_point_set@1.0"
    assert body["project"]["id"] == str(project.id)
    assert body["workbench"]["task"]["id"] == str(task.id)
    assert body["workbench"]["task"]["key"] == task.task_no
    assert body["entryPoint"] == {
        "action": "LOAD_TASK_CONTEXT",
        "method": "GET",
        "path": f"/external/v1/tasks/{task.id}",
        "taskId": str(task.id),
        "taskKey": task.task_no,
        "stage": "test-points",
        "artifactType": "test_point_set@1.0",
    }
    assert body["candidates"] == []
    submissions_after = db.scalar(select(func.count()).select_from(CandidateSubmission))
    assert submissions_after == submissions_before
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_requirement_with_multiple_tasks_requires_selection(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    login_requirement = workbench_handshake_context["login_requirement"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Requirement Selection Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续处理REQ-21001"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEEDS_SELECTION"
    assert body["entryPoint"] is None
    assert body["workbench"]["requirement"]["id"] == str(login_requirement.id)
    assert {item["key"] for item in body["candidates"]} == {
        "TASK-LOGIN-001",
        "TASK-LOGIN-002",
    }
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_blocked_task_returns_blocked_without_executable_entry(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context["payment_task"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Blocked Task Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续 TASK-PAY-001 的用例生成"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["entryPoint"] is None
    assert body["workbench"]["task"]["id"] == str(task.id)
    assert body["blockers"] == [
        {
            "code": "TASK_BLOCKED",
            "message": "测试任务当前处于 BLOCKED 状态，需要先解除阻塞",
        }
    ]
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_fixture_key", "message", "blocker_code"),
    [
        ("execution_task", "继续TASK-EXEC-001的测试用例", "UNSUPPORTED_TASK_TYPE"),
        ("unlinked_task", "继续TASK-NO-REQ-001的测试用例", "TASK_REQUIREMENT_REQUIRED"),
    ],
)
async def test_task_that_cannot_start_ai_design_returns_blocked(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    task_fixture_key: str,
    message: str,
    blocker_code: str,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context[task_fixture_key]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name=f"Blocked AI Design {task.task_no}",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": message},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["entryPoint"] is None
    assert body["workbench"]["task"]["id"] == str(task.id)
    assert [blocker["code"] for blocker in body["blockers"]] == [blocker_code]
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_first_message_content_matches_related_task_without_business_key(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context["payment_task"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Content Match Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续做订单支付的测试用例"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["intent"]["stage"] == "test-cases"
    assert body["workbench"]["task"]["id"] == str(task.id)
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_ambiguous_first_message_content_returns_task_candidates(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Ambiguous Content Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续登录相关测试"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEEDS_SELECTION"
    assert body["entryPoint"] is None
    assert {item["key"] for item in body["candidates"]} == {
        "TASK-LOGIN-001",
        "TASK-LOGIN-002",
    }
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_unmatched_specific_message_does_not_fallback_to_recent_task(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Unmatched Specific Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续做远航补给校准的测试用例"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_FOUND"
    assert body["workbench"] is None
    assert body["entryPoint"] is None
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_generic_continue_uses_most_recent_active_owned_task(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context["login_task"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Continue Recent Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续上次工作"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["workbench"]["task"]["id"] == str(task.id)
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_generic_continue_does_not_select_another_users_task(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    project = workbench_handshake_context["project"]
    viewer = User(
        email=f"viewer_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"viewer_{uuid.uuid4().hex[:6]}",
        display_name="No Task Viewer",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(viewer)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=viewer.id,
            role_id="project_admin",
        )
    )
    db.commit()

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="No Owned Task Token",
        project_id=project.id,
        user_id=viewer.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续上次工作"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_FOUND"
    assert body["workbench"] is None
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_explicit_cross_project_task_is_not_disclosed(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Project Isolation Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续处理 TASK-SECRET-001"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_FOUND"
    assert body["workbench"] is None
    assert body["entryPoint"] is None
    assert body["candidates"] == []
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "candidate_type", "candidate_key", "blocker_code"),
    [
        (
            "比较TASK-LOGIN-001和TASK-UNKNOWN-999的测试点",
            "TASK",
            "TASK-LOGIN-001",
            "UNRESOLVED_TASK_KEYS",
        ),
        (
            "比较REQ-21002和REQ-99999",
            "REQUIREMENT",
            "REQ-21002",
            "UNRESOLVED_REQUIREMENT_KEYS",
        ),
    ],
)
async def test_multiple_explicit_keys_never_ignore_unresolved_key(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    candidate_type: str,
    candidate_key: str,
    blocker_code: str,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name=f"Multiple Keys {candidate_type}",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": message},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEEDS_SELECTION"
    assert body["entryPoint"] is None
    assert [(item["type"], item["key"]) for item in body["candidates"]] == [
        (candidate_type, candidate_key)
    ]
    assert [blocker["code"] for blocker in body["blockers"]] == [blocker_code]
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scopes",
    [
        [],
        ["test_task.read"],
        ["requirement.read"],
        ["workspace:spec"],
        ["revision:candidate"],
    ],
)
async def test_workbench_handshake_requires_read_scope(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    scopes: list[str],
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="No Read Scope Token",
        project_id=project.id,
        user_id=user.id,
        scopes=scopes,
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续处理 TASK-LOGIN-001"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "SCOPE_PERMISSION_DENIED"
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_waiting_human_ai_design_blocks_direct_execution_and_restores_stage(
    db: Session,
    workbench_handshake_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    user = workbench_handshake_context["user"]
    project = workbench_handshake_context["project"]
    task = workbench_handshake_context["login_task"]
    record, _created = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="gateway-workbench-waiting-human",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    record.last_opened_stage = "test-points"
    run.status = "WAITING_HUMAN"
    db.commit()

    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Waiting Human Token",
        project_id=project.id,
        user_id=user.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=_create_test_app(db))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/external/v1/workbench/resolve",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"message": "继续上次工作"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["entryPoint"] is None
    assert body["intent"]["stage"] == "test-points"
    assert body["intent"]["artifactType"] == "test_point_set@1.0"
    assert body["workbench"]["aiDesign"]["recordId"] == str(record.id)
    assert body["workbench"]["aiDesign"]["runStatus"] == "WAITING_HUMAN"
    assert body["blockers"] == [
        {
            "code": "WAITING_HUMAN",
            "message": "当前 AI 测试设计记录正在等待人工确认",
        }
    ]
    get_external_agent_config.cache_clear()
