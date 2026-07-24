import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import AICapability, Project, ProjectMember, User
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.draft_sync_service import (
    DraftSyncService,
)
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


@pytest.fixture
def draft_test_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"draft_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"draft_{uuid.uuid4().hex[:6]}",
        display_name="Draft Admin User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Draft Project {uuid.uuid4().hex[:6]}",
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
        name="Draft Sync Capability",
        category="TEST_POINT_GENERATION",
    )
    db.add(capability)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "capability": capability,
    }


def test_draft_sync_service(db: Session, draft_test_context: dict) -> None:
    admin = draft_test_context["admin"]
    project = draft_test_context["project"]
    cap = draft_test_context["capability"]

    res = DraftSyncService.sync_capability_draft(
        db,
        token_project_id=project.id,
        user_id=admin.id,
        effective_scopes=["workspace:spec"],
        capability_id=cap.id,
        version_name="0.0.1-draft",
        files_snapshot={"files": [{"path": "main.py", "content": "# draft code"}]},
    )
    assert res["status"] == "SYNCED"
    assert res["versionName"] == "0.0.1-draft"


@pytest.mark.anyio
async def test_external_gateway_sync_draft_api(
    db: Session, draft_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = draft_test_context["admin"]
    project = draft_test_context["project"]
    cap = draft_test_context["capability"]

    from testweave.api.dependencies.database import get_db

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Draft Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["workspace:spec"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/external/v1/capabilities/sync-draft",
            json={
                "capabilityId": str(cap.id),
                "versionName": "1.0.0-draft",
                "filesSnapshot": {"files": []},
            },
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "SYNCED"

    get_external_agent_config.cache_clear()
