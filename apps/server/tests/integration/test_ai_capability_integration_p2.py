import uuid

import pytest
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilityVersion,
    Project,
    User,
)
from testweave.modules.ai_capability.enums import (
    AIRunMode,
    CapabilityRunStatus,
    HumanAction,
    StepExecutionStatus,
)
from testweave.modules.ai_capability.runtime.config import AIProviderSettings, AIRuntimeSettings
from testweave.modules.ai_capability.runtime.provider import FakeModelProvider
from testweave.modules.ai_capability.runtime.schemas import (
    AIRunCreateRequest,
    HumanDecisionSubmitRequest,
)
from testweave.modules.ai_capability.runtime.service import AIRuntimeService
from testweave.modules.ai_capability.runtime.worker import AIRuntimeWorker

pytestmark = pytest.mark.integration


@pytest.fixture
def p2_setup(db: Session) -> tuple[User, Project, AICapability, AICapabilityVersion]:
    admin = User(
        id=uuid.uuid4(),
        username="admin_p2",
        email="admin_p2@e2e.com",
        display_name="Admin P2",
        hashed_password="1",
        is_system_admin=True,
        status="active",
    )
    db.add(admin)

    project = Project(
        id=uuid.uuid4(),
        key="P2PROJ",
        name="P2 Project",
        owner_id=admin.id,
    )
    db.add(project)

    cap = AICapability(
        id=uuid.uuid4(),
        namespace=f"project/{str(project.id).lower()}",
        code="test-design-p2",
        name="测试点设计能力 P2",
        category="test_design",
        scope="PROJECT",
        project_id=project.id,
    )
    db.add(cap)

    workflow_def = {
        "nodes": {
            "req_modeling": {
                "type": "SKILL",
                "name": "需求建模",
                "input": "capability.input",
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "questions": {"type": "array", "items": {"type": "string"}},
                        "req_summary": {"type": "string"},
                    },
                    "required": ["questions", "req_summary"],
                },
            },
            "human_confirmation": {
                "type": "HUMAN",
                "name": "人工确认",
                "input": "req_modeling.output#/questions",
                "decision_schema": {
                    "type": "object",
                    "properties": {"approved": {"type": "boolean"}},
                    "required": ["approved"],
                },
            },
            "test_point_gen": {
                "type": "SKILL",
                "name": "测试点生成",
                "input": {
                    "summary": "req_modeling.output#/req_summary",
                    "decision": "human_confirmation.output",
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "test_points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "source_reference": {"type": "string"},
                                },
                            },
                        }
                    },
                    "required": ["test_points"],
                },
            },
            "test_point_val": {
                "type": "VALIDATOR",
                "name": "测试点校验",
                "input": "test_point_gen.output",
                "rules": ["every_item_has_source_reference"],
            },
        }
    }

    cap_ver = AICapabilityVersion(
        id=uuid.uuid4(),
        capability_id=cap.id,
        version="0.2.0",
        status="SYNCED_DRAFT",
        compatibility_level="PLATFORM_NATIVE",
        workflow_snapshot=workflow_def,
        input_schema={
            "type": "object",
            "properties": {"requirement_text": {"type": "string"}},
            "required": ["requirement_text"],
        },
    )
    db.add(cap_ver)

    package = AICapabilityPackage(
        capability_version_id=cap_ver.id,
        package_fingerprint="fingerprint_p2_020",
        validation_report={"valid": True},
        files_snapshot={
            "SKILL.md": "PROMPT_MOCK_TEST",
            "workflow.json": workflow_def,
        },
    )
    db.add(package)
    db.commit()

    return admin, project, cap, cap_ver


@pytest.mark.anyio
async def test_p2_runtime_end_to_end_flow(
    db: Session, p2_setup: tuple[User, Project, AICapability, AICapabilityVersion]
) -> None:
    admin, project, cap, cap_ver = p2_setup
    runtime_settings = AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True)

    # 1. 发起预览运行
    req = AIRunCreateRequest(
        runMode=AIRunMode.PREVIEW,
        capabilityVersionId=cap_ver.id,
        input={"requirement_text": "实现登录图形验证码校验功能"},
    )
    idemp_key = "idemp-key-test-001"

    run, is_created = AIRuntimeService.create_run(
        db=db,
        project_id=project.id,
        capability_id=cap.id,
        request=req,
        idempotency_key=idemp_key,
        actor_id=admin.id,
        actor_permissions={"agent.manage", "agent.use"},
        runtime_settings=runtime_settings,
    )
    assert is_created is True
    assert run.status == CapabilityRunStatus.PENDING

    # 再次使用相同 Idempotency-Key 幂等调用
    run_same, is_created_same = AIRuntimeService.create_run(
        db=db,
        project_id=project.id,
        capability_id=cap.id,
        request=req,
        idempotency_key=idemp_key,
        actor_id=admin.id,
        actor_permissions={"agent.manage", "agent.use"},
        runtime_settings=runtime_settings,
    )
    assert is_created_same is False
    assert run_same.id == run.id

    # 2. Worker 调度执行 Step 1 (req_modeling SKILL)
    fake_responses = {
        "PROMPT_MOCK_TEST": {
            "req_summary": "登录图形验证码",
            "questions": ["验证码刷新的频率是多少？"],
            "test_points": [{"id": 1, "source_reference": "REQ-10005"}],
        }
    }
    fake_provider = FakeModelProvider(fake_responses)
    worker = AIRuntimeWorker(
        db, runtime_settings, AIProviderSettings(), custom_provider=fake_provider
    )

    # 执行 Worker 直至到达挂起或就绪就绪空闲
    while await worker.run_once():
        pass

    # 查看 Run 状态 -> 应该到达 WAITING_HUMAN
    detail1 = AIRuntimeService.get_run_detail(
        db, project.id, run.id, admin.id, {"agent.manage", "agent.use"}
    )
    assert detail1.status == CapabilityRunStatus.WAITING_HUMAN
    assert "submitHumanDecision" in detail1.allowedActions

    human_step = next(s for s in detail1.steps if s.nodeId == "human_confirmation")
    assert human_step.status == StepExecutionStatus.WAITING_HUMAN

    # 3. 提交 Human Decision
    human_req = HumanDecisionSubmitRequest(
        action=HumanAction.CONTINUE,
        decision={"approved": True},
    )
    AIRuntimeService.submit_human_decision(
        db=db,
        project_id=project.id,
        run_id=run.id,
        step_execution_id=human_step.id,
        request=human_req,
        actor_id=admin.id,
        actor_permissions={"agent.manage", "agent.use"},
    )

    # 4. 再次触发 Worker 调度后续节点 (Human -> test_point_gen -> test_point_val)
    while await worker.run_once():
        pass

    # 5. 校验完成终态 SUCCEEDED
    detail2 = AIRuntimeService.get_run_detail(
        db, project.id, run.id, admin.id, {"agent.manage", "agent.use"}
    )
    assert detail2.status == CapabilityRunStatus.SUCCEEDED
    assert detail2.finalOutputSnapshot is not None
    assert "test_points" in detail2.finalOutputSnapshot

    # 6. 验证事件流游标轮询
    events_resp = AIRuntimeService.poll_events(db, project.id, run.id, after_sequence=0, limit=100)
    assert len(events_resp.items) >= 4
    assert events_resp.items[0].sequence == 1
    assert events_resp.items[0].eventType == "RUN_CREATED"


@pytest.mark.anyio
async def test_p2_cancel_and_retry_flow(
    db: Session, p2_setup: tuple[User, Project, AICapability, AICapabilityVersion]
) -> None:
    admin, project, cap, cap_ver = p2_setup
    runtime_settings = AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True)

    # 1. 发起运行
    req = AIRunCreateRequest(
        runMode=AIRunMode.PREVIEW,
        capabilityVersionId=cap_ver.id,
        input={"requirement_text": "取消与重试流测试"},
    )
    run, _ = AIRuntimeService.create_run(
        db=db,
        project_id=project.id,
        capability_id=cap.id,
        request=req,
        idempotency_key="idemp-key-test-cancel",
        actor_id=admin.id,
        actor_permissions={"agent.manage"},
        runtime_settings=runtime_settings,
    )

    # 2. 直接发起取消请求 (处于 PENDING 阶段无活动并发 Step，应直接转化为 CANCELLED)
    res_cancel = AIRuntimeService.cancel_run(
        db=db,
        project_id=project.id,
        run_id=run.id,
        actor_id=admin.id,
        actor_permissions={"agent.manage"},
    )
    assert res_cancel.status == CapabilityRunStatus.CANCELLED
    assert res_cancel.cancelRequested is True
