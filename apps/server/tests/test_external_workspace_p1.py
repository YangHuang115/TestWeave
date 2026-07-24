import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilityVersion,
    Project,
    ProjectMember,
    User,
)
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.modules.ai_capability.external_agent.workspace_generator import (
    LocalWorkspaceGenerator,
)
from testweave.modules.ai_capability.external_agent.workspace_spec_service import (
    WorkspaceSpecService,
)


@pytest.fixture
def workspace_test_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"admin_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"admin_{uuid.uuid4().hex[:6]}",
        display_name="Admin User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Workspace Project {uuid.uuid4().hex[:6]}",
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
        name="Workspace Generator Capability",
        category="TEST_POINT_GENERATION",
    )
    db.add(capability)
    db.commit()

    version = AICapabilityVersion(
        capability_id=capability.id,
        version="1.0.0",
        compatibility_level="v1",
        status="PUBLISHED",
        workflow_snapshot={},
        input_schema={"type": "object", "properties": {"req": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"test_points": {"type": "array"}}},
        package_fingerprint="sha256_mock_fingerprint",
        created_source="MANUAL",
    )
    db.add(version)
    db.commit()

    capability.current_published_version_id = version.id
    db.commit()

    pkg = AICapabilityPackage(
        capability_version_id=version.id,
        package_fingerprint="sha256_mock_fingerprint",
        files_snapshot={"files": [{"path": "package.json", "content": '{"name": "test-pkg"}'}]},
    )
    db.add(pkg)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "capability": capability,
        "version": version,
    }


def test_workspace_spec_service_generation(db: Session, workspace_test_context: dict) -> None:
    cap = workspace_test_context["capability"]
    _ver = workspace_test_context["version"]

    # 1. 缺乏 workspace:spec 校验抛错
    with pytest.raises(AppError) as exc_info:
        WorkspaceSpecService.generate_workspace_spec(
            db, target_id=cap.id, effective_scopes=["revision:candidate"]
        )
    assert exc_info.value.code == "SCOPE_PERMISSION_DENIED"

    # 2. 正常生成 Spec 格式与关键字段校验
    spec = WorkspaceSpecService.generate_workspace_spec(
        db, target_id=cap.id, effective_scopes=["workspace:spec"]
    )

    assert spec["specVersion"] == "1.0"
    assert spec["capability"]["id"] == str(cap.id)
    assert spec["capability"]["version"] == "1.0.0"
    assert spec["contract"]["inputSchema"]["type"] == "object"
    assert "test_point_set@1.0" in spec["contract"]["supportedArtifactTypes"]
    assert len(spec["templates"]["files"]) > 0


def test_local_workspace_generator(
    tmp_path: Any, db: Session, workspace_test_context: dict
) -> None:
    cap = workspace_test_context["capability"]

    spec = WorkspaceSpecService.generate_workspace_spec(
        db, target_id=cap.id, effective_scopes=["workspace:spec"]
    )

    output_dir = tmp_path / "gen_workspace"

    # 1. 在干净空目录成功生成文件
    files = LocalWorkspaceGenerator.generate_local_workspace(spec, output_dir)
    assert "spec.json" in files
    assert (output_dir / "spec.json").exists()
    assert (output_dir / "package.json").exists()

    # 2. 非空目录再次生成应该抛错
    with pytest.raises(AppError) as exc:
        LocalWorkspaceGenerator.generate_local_workspace(spec, output_dir)
    assert exc.value.code == "TARGET_DIRECTORY_NOT_EMPTY"


@pytest.mark.anyio
async def test_external_gateway_workspace_spec_api(
    db: Session, workspace_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = workspace_test_context["admin"]
    project = workspace_test_context["project"]
    cap = workspace_test_context["capability"]

    from httpx import ASGITransport, AsyncClient

    from testweave.api.dependencies.database import get_db
    from testweave.core.readiness import NotConfiguredReadinessProbe

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Workspace Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["workspace:spec"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get(
            f"/external/v1/workspace/spec?targetId={cap.id}",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["specVersion"] == "1.0"
        assert data["capability"]["key"] == cap.code

    get_external_agent_config.cache_clear()
