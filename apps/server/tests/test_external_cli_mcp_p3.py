import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from testweave.cli.external_agent_cli import ExternalAgentCLIClient
from testweave.db.models import AICapability, Project, ProjectMember, User
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


@pytest.fixture
def cli_test_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"cli_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"cli_{uuid.uuid4().hex[:6]}",
        display_name="CLI Admin User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"CLI Project {uuid.uuid4().hex[:6]}",
        key=f"PRJ_{uuid.uuid4().hex[:4]}".upper(),
        owner_id=admin.id,
    )
    db.add(project)
    db.commit()

    pm = ProjectMember(
        project_id=project.id,
        user_id=admin.id,
        role_id="project_admin",
    )
    db.add(pm)

    capability = AICapability(
        project_id=project.id,
        scope="PROJECT",
        namespace="testweave",
        code=f"cap_{uuid.uuid4().hex[:6]}",
        name="CLI Capability",
        category="TEST_POINT_GENERATION",
    )
    db.add(capability)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "capability": capability,
    }


def test_cli_client_initialization(db: Session, cli_test_context: dict) -> None:
    admin = cli_test_context["admin"]
    project = cli_test_context["project"]

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="CLI Test Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["workspace:spec", "revision:candidate"],
    )

    client = ExternalAgentCLIClient(gateway_url="http://127.0.0.1:8787", token=raw_token)
    assert client.token == raw_token
    assert client.headers["Authorization"] == f"Bearer {raw_token}"


def test_cli_client_resolves_and_executes_ready_workbench_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ExternalAgentCLIClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path == "/external/v1/workbench/resolve":
            return {
                "status": "READY",
                "entryPoint": {
                    "action": "LOAD_TASK_CONTEXT",
                    "method": "GET",
                    "path": "/external/v1/tasks/11111111-1111-1111-1111-111111111111",
                    "taskId": "11111111-1111-1111-1111-111111111111",
                },
            }
        return {"id": "11111111-1111-1111-1111-111111111111"}

    monkeypatch.setattr(client, "_request", fake_request)

    workbench = client.resolve_workbench("继续登录测试点设计")
    result = client.execute_workbench_entry(workbench)

    assert result["id"] == "11111111-1111-1111-1111-111111111111"
    assert calls == [
        (
            "POST",
            "/external/v1/workbench/resolve",
            {"message": "继续登录测试点设计"},
        ),
        (
            "GET",
            "/external/v1/tasks/11111111-1111-1111-1111-111111111111",
            None,
        ),
    ]


@pytest.mark.parametrize(
    "workbench",
    [
        {"status": "BLOCKED", "entryPoint": None},
        {
            "status": "READY",
            "entryPoint": {
                "action": "LOAD_TASK_CONTEXT",
                "method": "POST",
                "path": "/external/v1/revision/candidates",
            },
        },
        {
            "status": "READY",
            "entryPoint": {
                "action": "LOAD_TASK_CONTEXT",
                "method": "GET",
                "path": "https://example.com/exfiltrate",
            },
        },
        {
            "status": "READY",
            "entryPoint": {
                "action": "LOAD_TASK_CONTEXT",
                "method": "GET",
                "path": "/external/v1/tasks/..",
                "taskId": "..",
            },
        },
    ],
)
def test_cli_client_refuses_non_ready_or_unsafe_workbench_entry(
    workbench: dict[str, Any],
) -> None:
    client = ExternalAgentCLIClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )

    with pytest.raises(ValueError):
        client.execute_workbench_entry(workbench)
