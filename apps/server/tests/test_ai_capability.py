import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityRun,
    AICapabilityVersion,
    AIStepExecution,
    AuditEvent,
)
from testweave.modules.ai_capability.assembly import (
    ExternalAgentModule,
    setup_external_agent_module,
)
from testweave.modules.ai_capability.config import ExternalAgentFeatureConfig
from testweave.modules.ai_capability.enums import (
    AICapabilityStatus,
    CapabilityRunStatus,
    CapabilityScope,
    CapabilityVersionStatus,
    StepExecutionStatus,
)
from testweave.modules.ai_capability.events import RunEventEnvelope
from testweave.modules.audit.service import AuditService
from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService


def test_external_agent_config_defaults() -> None:
    config = ExternalAgentFeatureConfig()
    assert config.enabled is False
    assert config.bind_host == "127.0.0.1"
    assert config.port == 8787


def test_external_agent_config_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__BIND_HOST", "::1")
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__PORT", "9090")

    config = ExternalAgentFeatureConfig()
    assert config.enabled is True
    assert config.bind_host == "::1"
    assert config.port == 9090


def test_external_agent_config_invalid_host() -> None:
    with pytest.raises(ValidationError) as exc_info_all:
        ExternalAgentFeatureConfig(enabled=True, bind_host="0.0.0.0", port=8787)
    assert "loopback" in str(exc_info_all.value)

    with pytest.raises(ValidationError) as exc_info_v6:
        ExternalAgentFeatureConfig(enabled=True, bind_host="::", port=8787)
    assert "loopback" in str(exc_info_v6.value)


def test_setup_external_agent_module_two_states() -> None:
    # 1. enabled=False -> None
    config_disabled = ExternalAgentFeatureConfig(enabled=False)
    mod_disabled = setup_external_agent_module(config_disabled)
    assert mod_disabled is None

    # 2. enabled=True -> ExternalAgentModule pure descriptor
    config_enabled = ExternalAgentFeatureConfig(enabled=True, bind_host="127.0.0.1", port=8787)
    mod_enabled = setup_external_agent_module(config_enabled)
    assert isinstance(mod_enabled, ExternalAgentModule)
    assert mod_enabled.enabled is True
    assert mod_enabled.bind_host == "127.0.0.1"
    assert mod_enabled.port == 8787


@pytest.mark.anyio
async def test_app_has_no_agent_v1_routes_and_no_side_effects() -> None:
    from httpx import ASGITransport, AsyncClient

    from testweave.main import app

    # 1. 检查 FastAPI app 注册路由中绝无 /agent/v1 前缀
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert not any(p.startswith("/agent/v1") for p in route_paths)

    # 2. 发起请求 /agent/v1/health 必须返回 404
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        response = await ac.get("/agent/v1/health")
        assert response.status_code == 404


def test_run_event_envelope_validation() -> None:
    run_id = uuid.uuid4()
    now_utc = datetime.now(UTC)

    # 成功构建合法事件
    event = RunEventEnvelope(
        event_id=uuid.uuid4(),
        event_type="STEP_COMPLETED",
        run_id=run_id,
        sequence=1,
        occurred_at=now_utc,
        trace_id="tr-1001",
        payload={"result": "ok"},
    )
    assert event.sequence == 1
    assert event.schema_version == "1.0"
    assert event.payload["result"] == "ok"

    # 校验 sequence 必须 > 0
    with pytest.raises(ValidationError):
        RunEventEnvelope(
            event_id=uuid.uuid4(),
            event_type="STEP_COMPLETED",
            run_id=run_id,
            sequence=0,
            occurred_at=now_utc,
            trace_id="tr-1001",
        )

    # 校验 occurred_at 必须带时区
    with pytest.raises(ValidationError):
        RunEventEnvelope(
            event_id=uuid.uuid4(),
            event_type="STEP_COMPLETED",
            run_id=run_id,
            sequence=1,
            occurred_at=datetime.now(),  # naive datetime
            trace_id="tr-1001",
        )


def test_domain_enums_isolation() -> None:
    assert CapabilityScope.OFFICIAL == "OFFICIAL"
    assert CapabilityScope.PROJECT == "PROJECT"

    assert AICapabilityStatus.ACTIVE == "ACTIVE"
    assert AICapabilityStatus.ARCHIVED == "ARCHIVED"

    assert CapabilityVersionStatus.PUBLISHED == "PUBLISHED"
    assert CapabilityRunStatus.RUNNING == "RUNNING"
    assert StepExecutionStatus.SKIPPED == "SKIPPED"

    # StepExecutionStatus 额外增含 SKIPPED，与 RunStatus 区分
    assert "SKIPPED" in [s.value for s in StepExecutionStatus]
    assert "SKIPPED" not in [r.value for r in CapabilityRunStatus]


@pytest.fixture
def ai_test_context(db: Session) -> dict[str, Any]:
    user = UserService.create_user(
        db, username="ai_owner", email="ai@tw.com", display_name="AI Owner", password="pwd"
    )
    db.commit()

    project = ProjectService.create_project(
        db, key="AIPROJ", name="AI Project", owner_id=user.id, request_id="req-p"
    )
    db.commit()
    return {"user": user, "project": project}


def test_ai_capability_orm_constraints(db: Session, ai_test_context: dict[str, Any]) -> None:
    user = ai_test_context["user"]
    project = ai_test_context["project"]

    # 1. 成功创建 OFFICIAL 能力 (无 project_id)
    cap_official = AICapability(
        namespace="official.test",
        code="code_gen",
        name="Official Code Gen",
        category="code",
        scope=CapabilityScope.OFFICIAL.value,
        project_id=None,
    )
    db.add(cap_official)
    db.commit()
    assert cap_official.id is not None

    # 2. 成功创建 PROJECT 能力 (必含 project_id)
    cap_proj = AICapability(
        namespace="custom.project",
        code="custom_step",
        name="Project Custom Step",
        category="custom",
        scope=CapabilityScope.PROJECT.value,
        project_id=project.id,
    )
    db.add(cap_proj)
    db.commit()

    # 3. 校验唯一约束 (namespace, code)
    cap_dup = AICapability(
        namespace="official.test",
        code="code_gen",
        name="Duplicate Code Gen",
        category="code",
        scope=CapabilityScope.OFFICIAL.value,
    )
    db.add(cap_dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 4. 创建版本与运行关联
    version = AICapabilityVersion(
        capability_id=cap_official.id,
        version="1.0.0",
        status=CapabilityVersionStatus.PUBLISHED.value,
        created_source="MANUAL",
        created_by=user.id,
    )
    db.add(version)
    db.commit()

    # 设置循环外键 current_published_version_id
    cap_official.current_published_version_id = version.id
    db.commit()
    assert cap_official.current_published_version is not None
    assert cap_official.current_published_version.version == "1.0.0"

    # 5. 创建 CapabilityRun 与 StepExecution
    run = AICapabilityRun(
        capability_version_id=version.id,
        project_id=project.id,
        initiator_id=user.id,
        trace_id="trace-ai-1001",
        status=CapabilityRunStatus.RUNNING.value,
        input_snapshot={"prompt": "test"},
    )
    db.add(run)
    db.commit()

    step = AIStepExecution(
        run_id=run.id,
        node_id="node_1",
        attempt=1,
        status=StepExecutionStatus.SUCCEEDED.value,
    )
    db.add(step)
    db.commit()

    # 校验 (run_id, node_id, attempt) 唯一约束
    step_dup = AIStepExecution(
        run_id=run.id,
        node_id="node_1",
        attempt=1,
        status=StepExecutionStatus.FAILED.value,
    )
    db.add(step_dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_service_transaction_integration(
    db: Session, ai_test_context: dict[str, Any]
) -> None:
    user = ai_test_context["user"]
    project = ai_test_context["project"]

    # 事务 1：提交审计与 AI 能力创建，双双持久化
    cap = AICapability(
        namespace="audit.test",
        code="audit_cap",
        name="Audit Test Cap",
        category="audit",
        scope=CapabilityScope.PROJECT.value,
        project_id=project.id,
    )
    db.add(cap)
    db.flush()

    AuditService.log_event(
        db,
        action="ai_capability.created",
        object_type="AICapability",
        object_id=str(cap.id),
        summary=f"创建了 AI 能力 '{cap.name}'",
        actor_id=user.id,
        project_id=project.id,
        request_id="req-audit-1",
    )
    db.commit()

    audit_entry = db.scalar(
        select(AuditEvent).where(
            AuditEvent.object_type == "AICapability",
            AuditEvent.object_id == str(cap.id),
        )
    )
    assert audit_entry is not None
    assert audit_entry.action == "ai_capability.created"

    # 事务 2：显式回滚场景，审计日志与业务变动同时清除
    cap_rollback = AICapability(
        namespace="audit.test",
        code="rollback_cap",
        name="Rollback Cap",
        category="audit",
        scope=CapabilityScope.PROJECT.value,
        project_id=project.id,
    )
    db.add(cap_rollback)
    db.flush()

    AuditService.log_event(
        db,
        action="ai_capability.created",
        object_type="AICapability",
        object_id=str(cap_rollback.id),
        summary="待回滚的操作",
        actor_id=user.id,
        project_id=project.id,
        request_id="req-audit-2",
    )
    db.rollback()

    # 验证数据库中均无此记录
    assert db.scalar(select(AICapability).where(AICapability.code == "rollback_cap")) is None
    assert db.scalar(select(AuditEvent).where(AuditEvent.object_id == str(cap_rollback.id))) is None
