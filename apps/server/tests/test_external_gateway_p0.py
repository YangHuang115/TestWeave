import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import ProjectMember
from testweave.main import create_app
from testweave.modules.ai_capability.config import ExternalAgentFeatureConfig
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


def test_external_agent_config_loopback_validation() -> None:
    # 允许回环
    cfg1 = ExternalAgentFeatureConfig(bind_host="127.0.0.1")
    assert cfg1.bind_host == "127.0.0.1"

    cfg2 = ExternalAgentFeatureConfig(bind_host="localhost")
    assert cfg2.bind_host == "localhost"

    cfg3 = ExternalAgentFeatureConfig(bind_host="::1")
    assert cfg3.bind_host == "::1"

    # 拒绝公网绑定
    with pytest.raises(ValidationError) as exc:
        ExternalAgentFeatureConfig(bind_host="0.0.0.0")
    assert "loopback" in str(exc.value)

    with pytest.raises(ValidationError) as exc2:
        ExternalAgentFeatureConfig(bind_host="192.168.1.100")
    assert "loopback" in str(exc2.value)


@pytest.fixture
def gateway_test_context(db: Session) -> dict:
    from testweave.db.base import Base
    from testweave.modules.projects.service import ProjectService
    from testweave.modules.users.service import UserService

    Base.metadata.create_all(bind=db.get_bind())

    user_admin = UserService.create_user(
        db,
        username=f"gw_admin_{uuid.uuid4().hex[:6]}",
        password="Password123!",
        email=f"gw_admin_{uuid.uuid4().hex[:6]}@example.com",
        display_name="GW Admin",
    )
    user_viewer = UserService.create_user(
        db,
        username=f"gw_viewer_{uuid.uuid4().hex[:6]}",
        password="Password123!",
        email=f"gw_viewer_{uuid.uuid4().hex[:6]}@example.com",
        display_name="GW Viewer",
    )
    project = ProjectService.create_project(
        db,
        name=f"GW Project {uuid.uuid4().hex[:6]}",
        key=f"GWP{uuid.uuid4().hex[:4].upper()}",
        owner_id=user_admin.id,
        request_id=f"req_{uuid.uuid4().hex[:8]}",
    )

    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user_viewer.id,
            role_id="project_viewer",
        )
    )
    db.commit()
    return {
        "admin": user_admin,
        "viewer": user_viewer,
        "project": project,
    }


def test_token_lifecycle_and_scope_intersection(
    db: Session, gateway_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    _admin = gateway_test_context["admin"]
    viewer = gateway_test_context["viewer"]
    project = gateway_test_context["project"]

    # 1. 尝试使用非法 scope 创建 token
    with pytest.raises(AppError) as exc_scope:
        ExternalAgentTokenService.create_token(
            db,
            name="Invalid Scope Token",
            project_id=project.id,
            user_id=viewer.id,
            scopes=["workspace:spec", "invalid:scope"],
        )
    assert exc_scope.value.code == "INVALID_TOKEN_SCOPE"

    # 2. 由 viewer 用户申请包含写权限的 Token (申明 scopes: workspace:spec, revision:candidate)
    token_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Viewer Token",
        project_id=project.id,
        user_id=viewer.id,
        scopes=["workspace:spec", "revision:candidate"],
    )
    assert raw_token.startswith("tw_ext_")

    # 3. 校验 authenticate_token 权限实时交集计算
    # 虽然 Token 申请了 revision:candidate (需 EDITOR)，但用户角色是 VIEWER，生效 scopes 必须只包含 workspace:spec
    _tok, _usr, role, eff_scopes = ExternalAgentTokenService.authenticate_token(db, raw_token)
    assert _tok.id == token_obj.id
    assert role == "VIEWER"
    assert eff_scopes == ["workspace:spec"]

    # 4. 提升用户为 EDITOR 角色后，生效 scopes 实时自动增加 revision:candidate
    from sqlalchemy import select

    pm = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == viewer.id,
        )
    )
    assert pm is not None
    pm.role_id = "project_editor"
    db.commit()

    _tok2, _usr2, role2, eff_scopes2 = ExternalAgentTokenService.authenticate_token(db, raw_token)
    assert role2 == "EDITOR"
    assert set(eff_scopes2) == {"workspace:spec", "revision:candidate"}

    # 5. 测试 Token 撤销
    ExternalAgentTokenService.revoke_token(db, token_obj.id, project.id)
    with pytest.raises(AppError) as exc_rev:
        ExternalAgentTokenService.authenticate_token(db, raw_token)
    assert exc_rev.value.code == "TOKEN_REVOKED"

    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_external_gateway_api_endpoints(
    db: Session, gateway_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = gateway_test_context["admin"]
    project = gateway_test_context["project"]

    from httpx import ASGITransport, AsyncClient

    from testweave.api.dependencies.database import get_db
    from testweave.core.readiness import NotConfiguredReadinessProbe

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. 字典接口 GET /external/v1/token/scopes
        res_scopes = await client.get("/external/v1/token/scopes")
        assert res_scopes.status_code == 200
        assert "workspace:spec" in res_scopes.json()["scopes"]

        # 2. 生成有效 Token
        _token_obj, raw_token = ExternalAgentTokenService.create_token(
            db,
            name="API Test Token",
            project_id=project.id,
            user_id=admin.id,
            scopes=["workspace:spec", "revision:candidate"],
        )

        # 3. GET /external/v1/session
        res_sess = await client.get(
            "/external/v1/session",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_sess.status_code == 200
        data = res_sess.json()
        assert data["valid"] is True
        assert data["projectId"] == str(project.id)
        assert data["userRole"] in ("ADMIN", "OWNER")

    get_external_agent_config.cache_clear()
