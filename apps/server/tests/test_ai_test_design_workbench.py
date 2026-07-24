import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.v1.ai_test_design import get_runtime_settings
from testweave.core.errors import AppError
from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import (
    AIArtifactItem,
    AIArtifactRevision,
    AIArtifactSetRevision,
    AICapabilityRun,
    AIContextSnapshot,
    AICurrentAcceptedRevisionSet,
    AIDependencyEdge,
    AIHumanGateAction,
    AIRegenerationRequest,
    AIStepExecution,
    Project,
    ProjectMember,
    Requirement,
    RequirementAttachment,
    User,
    Version,
)
from testweave.db.models import (
    TestTask as DbTestTask,
)
from testweave.db.models import (
    TestTaskRequirement as DbTestTaskRequirement,
)
from testweave.main import create_app
from testweave.modules.ai_capability.revision import (
    AcceptanceService,
    FeedbackService,
    FieldLockService,
    RegenerationService,
    SetRevisionService,
)
from testweave.modules.ai_capability.runtime.config import AIProviderSettings, AIRuntimeSettings
from testweave.modules.ai_capability.runtime.provider import ModelProvider, ProviderResponse
from testweave.modules.ai_capability.runtime.worker import AIRuntimeWorker
from testweave.modules.ai_test_design.query_service import AiTestDesignQueryService
from testweave.modules.ai_test_design.revision_service import AiTestDesignRevisionService
from testweave.modules.ai_test_design.service import AiTestDesignService


class _CapturingRegenerationProvider(ModelProvider):
    def __init__(self, replacement: dict) -> None:
        self.replacement = replacement
        self.calls: list[dict] = []

    async def invoke_structured_json(
        self,
        instructions: str,
        input_data: dict,
        output_schema: dict,
        model_policy: str = "quality_first",
        timeout_seconds: int = 120,
        max_output_bytes: int = 2097152,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "instructions": instructions,
                "input": input_data,
                "schema": output_schema,
            }
        )
        return ProviderResponse(
            content_json={
                "replacements": [
                    {
                        "targetRef": "target-requirement-analysis",
                        "content": self.replacement,
                    }
                ]
            },
            provider_name="capture",
            model_name="capture-model",
        )


class _FourStageProvider(ModelProvider):
    async def invoke_structured_json(
        self,
        instructions: str,
        input_data: dict,
        output_schema: dict,
        model_policy: str = "quality_first",
        timeout_seconds: int = 120,
        max_output_bytes: int = 2097152,
    ) -> ProviderResponse:
        if "需求分析智能体" in instructions:
            content = _analysis_payload("PENDING")
        elif "测试点设计智能体" in instructions:
            content = {
                "schemaVersion": "1.0",
                "points": [
                    {
                        "stableKey": "TP-001",
                        "title": "连续失败五次锁定账号",
                        "description": "覆盖失败计数边界",
                        "module": "账号",
                        "scope": "安全",
                        "preconditions": ["账号未锁定"],
                        "coreAction": "连续五次输入错误密码",
                        "coreExpected": "账号被锁定",
                        "variables": [{"name": "失败次数", "partitions": ["4", "5", "6"]}],
                        "testMethod": "边界值",
                        "testMethodReason": "锁定规则存在明确次数边界",
                        "risk": "HIGH",
                        "priority": "HIGH",
                        "ruleRefs": [],
                        "questionRefs": ["Q-001"],
                        "moduleRelationRefs": [],
                        "allowCaseGeneration": True,
                    }
                ],
            }
        elif "测试用例设计智能体" in instructions:
            content = {
                "schemaVersion": "1.0",
                "cases": [
                    {
                        "stableKey": "TC-001",
                        "title": "第五次失败后锁定账号",
                        "module": "账号",
                        "scope": "安全",
                        "priority": "HIGH",
                        "primaryTestPointRef": "TP-001",
                        "ruleRefs": [],
                        "preconditions": ["账号未锁定", "已连续失败四次"],
                        "testData": [
                            {"name": "密码", "value": "wrong-5", "purpose": "触发第五次失败"}
                        ],
                        "steps": [
                            {
                                "stepNo": 1,
                                "action": "输入错误密码并登录",
                                "expected": "登录失败且账号进入锁定状态",
                            }
                        ],
                        "coreExpected": "第五次失败后账号被锁定",
                        "observationPoints": ["登录接口状态", "锁定提示"],
                        "cleanupActions": ["解除账号锁定"],
                        "testMethod": "边界值",
                        "assumptionRefs": [],
                        "qualityPrecheck": {"status": "PASS", "findings": []},
                    }
                ],
            }
        else:
            content = {
                "schemaVersion": "1.0",
                "stableKey": "case-review-report",
                "mode": "TRACEABLE",
                "gateRecommendation": "PASS_WITH_WARNINGS",
                "summary": "核心锁定路径可追踪",
                "caseResults": [
                    {"caseRef": "TC-001", "status": "WARNING", "findingRefs": ["F-001"]}
                ],
                "findings": [
                    {
                        "stableKey": "F-001",
                        "severity": "WARNING",
                        "caseRef": "TC-001",
                        "fieldPath": "/steps/0/expected",
                        "evidenceRefs": ["TP-001"],
                        "description": "缺少失败计数持久化观察",
                        "suggestion": "补充服务端失败计数观察点",
                        "decision": "PENDING",
                        "decisionReason": "",
                    }
                ],
                "coverage": {
                    "ruleCoverage": 1.0,
                    "testPointCoverage": 1.0,
                    "uncoveredRefs": [],
                },
                "duplicateClusters": [],
                "unresolvedAssumptions": [],
                "revisionRequests": [],
            }
        return ProviderResponse(
            content_json=content,
            provider_name="four-stage-test",
            model_name="four-stage-model",
        )


def _analysis_payload(question_status: str = "PENDING") -> dict:
    return {
        "schemaVersion": "1.0",
        "stableKey": "requirement-analysis",
        "goal": "验证登录需求",
        "inScope": ["密码登录"],
        "outOfScope": [],
        "modules": [],
        "moduleRelations": [],
        "rules": [],
        "inferences": [],
        "questions": [
            {
                "id": "Q-001",
                "question": "账号锁定多久？",
                "blocking": True,
                "status": question_status,
                "answer": "30 分钟" if question_status == "ANSWERED" else "",
                "decisionReason": "产品确认" if question_status == "ANSWERED" else "",
                "scope": "IN_SCOPE",
            }
        ],
        "risks": [],
        "evidence": [],
    }


def _create_case_design_task(
    db: Session,
) -> tuple[User, Project, DbTestTask, Requirement]:
    user = User(
        username=f"ai-design-{uuid.uuid4().hex[:8]}",
        email=f"ai-design-{uuid.uuid4().hex[:8]}@testweave.local",
        display_name="AI 设计用户",
        hashed_password="test-password",
    )
    db.add(user)
    db.flush()

    project = Project(
        key=f"AI{uuid.uuid4().hex[:6]}".upper(),
        name="AI 测试设计项目",
        owner_id=user.id,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_id="test_member",
        )
    )

    version = Version(
        project_id=project.id,
        key="0.0.1",
        key_normalized="0.0.1",
        name="0.0.1 demo版本",
        owner_id=user.id,
    )
    db.add(version)
    db.flush()

    requirement = Requirement(
        project_id=project.id,
        requirement_no="REQ-AI-DESIGN",
        requirement_no_normalized="req-ai-design",
        title="登录安全测试需求",
        description="密码连续错误五次后锁定账号。",
        acceptance_criteria="锁定后拒绝继续登录。",
        owner_id=user.id,
    )
    db.add(requirement)
    db.flush()

    now = datetime.now(UTC)
    task = DbTestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-AI-001",
        task_type="CASE_DESIGN",
        title="登录安全用例设计",
        owner_id=user.id,
        planned_start_at=now,
        planned_end_at=now + timedelta(days=1),
        created_by=user.id,
    )
    db.add(task)
    db.flush()
    db.add(
        DbTestTaskRequirement(
            task_id=task.id,
            requirement_id=requirement.id,
            linked_by=user.id,
        )
    )
    db.commit()
    return user, project, task, requirement


def test_create_and_resume_independent_chain_records(db: Session) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    runtime_settings = AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True)

    first, created = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-chain-1",
        runtime_settings=runtime_settings,
    )
    assert created is True
    assert first.record_no == 1
    assert first.task_id == task.id
    assert db.get(AICapabilityRun, first.run_id) is not None

    replay, replay_created = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-chain-1",
        runtime_settings=runtime_settings,
    )
    assert replay_created is False
    assert replay.id == first.id

    second, second_created = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-chain-2",
        runtime_settings=runtime_settings,
    )
    assert second_created is True
    assert second.record_no == 2

    resumed = AiTestDesignService.get_resume_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
    )
    assert resumed is not None
    assert resumed.id == second.id


def test_case_design_record_requires_one_linked_requirement(db: Session) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    db.query(DbTestTaskRequirement).filter_by(task_id=task.id).delete()
    db.commit()

    runtime_settings = AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True)

    try:
        AiTestDesignService.create_record(
            db=db,
            project_id=project.id,
            task_id=task.id,
            actor_id=user.id,
            actor_permissions={"agent.use"},
            idempotency_key="ai-design-missing-requirement",
            runtime_settings=runtime_settings,
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "AI_DESIGN_REQUIREMENT_REQUIRED"
    else:
        raise AssertionError("未关联需求时不应创建 AI 测试设计链")


def test_run_input_includes_bounded_attachment_text(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, task, requirement = _create_case_design_task(db)
    attachment = RequirementAttachment(
        project_id=project.id,
        requirement_id=requirement.id,
        original_filename="登录规则.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=128,
        sha256="a" * 64,
        storage_key=f"{project.id}/{requirement.id}/rules.docx",
        uploaded_by=user.id,
    )
    db.add(attachment)
    db.flush()
    monkeypatch.setattr(
        "testweave.modules.ai_test_design.service.extract_attachment_text",
        lambda _storage_key: "第五次失败后锁定账号",
    )

    run_input = AiTestDesignService._build_run_input(db, task, requirement, "TRACEABLE")

    assert run_input["attachments"][0]["fileName"] == "登录规则.docx"
    assert run_input["attachments"][0]["extractedText"] == "第五次失败后锁定账号"


def test_worker_materializes_only_declared_stage_artifact_projection(db: Session) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-projection",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    skill_step = (
        db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    )

    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    output = {
        "schemaVersion": "1.0",
        "stableKey": "requirement-analysis",
        "goal": "验证登录需求",
        "inScope": [],
        "outOfScope": [],
        "modules": [],
        "moduleRelations": [],
        "rules": [],
        "inferences": [],
        "questions": [],
        "risks": [],
        "evidence": [],
    }
    created_set = worker._materialize_p3_artifact_revision_set(db, run, skill_step, output)
    assert created_set is not None
    assert created_set.producer_node_id == "requirement_analysis"
    assert skill_step.output_revision_set_id == created_set.id

    item = (
        db.query(AIArtifactItem)
        .filter_by(run_id=run.id, producer_node_id="requirement_analysis")
        .one()
    )
    assert item.stable_key == "requirement-analysis"
    assert item.artifact_type == "requirement_analysis@1.0"

    gate_step = AIStepExecution(
        run_id=run.id,
        node_id="requirement_analysis_gate",
        node_type="HUMAN",
        attempt=1,
        status="RUNNING",
    )
    db.add(gate_step)
    db.flush()
    assert (
        worker._materialize_p3_artifact_revision_set(
            db, run, gate_step, {"acceptedSetRevisionId": str(created_set.id)}
        )
        is None
    )
    assert (
        db.query(AIArtifactSetRevision)
        .filter_by(run_id=run.id, producer_node_id="requirement_analysis_gate")
        .count()
        == 0
    )


def test_downstream_context_uses_current_accepted_full_set_and_rejects_stale(
    db: Session,
) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-context",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    analysis_step = (
        db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    )
    analysis_set = worker._materialize_p3_artifact_revision_set(
        db,
        run,
        analysis_step,
        {
            "schemaVersion": "1.0",
            "stableKey": "requirement-analysis",
            "goal": "验证登录需求",
            "inScope": [],
            "outOfScope": [],
            "modules": [],
            "moduleRelations": [],
            "rules": [],
            "inferences": [],
            "questions": [],
            "risks": [],
            "evidence": [],
        },
    )
    accepted = AcceptanceService.accept_set_revision(db, str(analysis_set.id), user_id=str(user.id))

    points_step = AIStepExecution(
        run_id=run.id,
        node_id="test_points",
        node_type="SKILL",
        attempt=1,
        status="RUNNING",
    )
    db.add(points_step)
    db.flush()
    node_def = run.execution_snapshot["workflow"]["nodes"]["test_points"]
    resolved = worker._augment_with_accepted_context(
        db, run, points_step, node_def, {"decision": {"approved": True}}
    )
    assert points_step.input_context_snapshot_id is not None
    assert resolved["acceptedUpstreamContext"]["requirement_analysis"][0]["goal"] == (
        "验证登录需求"
    )

    accepted.freshness_status = "STALE"
    stale_step = AIStepExecution(
        run_id=run.id,
        node_id="test_points",
        node_type="SKILL",
        attempt=2,
        status="RUNNING",
    )
    db.add(stale_step)
    db.flush()
    with pytest.raises(AppError) as exc:
        worker._augment_with_accepted_context(
            db, run, stale_step, node_def, {"decision": {"approved": True}}
        )
    assert exc.value.code == "CONTEXT_SOURCE_STALE"


def test_manual_edit_creates_immutable_item_revision_and_complete_set(db: Session) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-edit",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    step = db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    original_payload = _analysis_payload("PENDING")
    original_set = worker._materialize_p3_artifact_revision_set(db, run, step, original_payload)

    edited_payload = _analysis_payload("ANSWERED")
    edited_payload["goal"] = "验证登录与账号锁定需求"
    edited_set = AiTestDesignRevisionService.save_stage_revision(
        db=db,
        record=record,
        stage_key="requirement-analysis",
        base_set_revision_id=original_set.id,
        expected_set_hash=original_set.set_hash,
        items=[edited_payload],
        actor_id=user.id,
    )

    assert edited_set.set_revision_no == 2
    assert edited_set.base_set_revision_id == original_set.id
    assert edited_set.item_count == 1
    original_revision = db.query(AIArtifactRevision).filter_by(source="INITIAL_GENERATION").one()
    edited_revision = db.query(AIArtifactRevision).filter_by(source="USER_EDIT").one()
    assert original_revision.content == original_payload
    assert edited_revision.content == edited_payload
    assert edited_revision.artifact_item_id == original_revision.artifact_item_id

    feedback = FeedbackService.create_feedback(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        target_type="FIELD",
        category="事实错误",
        comment="人工补充锁定目标",
        target_item_id=str(edited_revision.artifact_item_id),
        target_revision_id=str(edited_revision.id),
        json_pointer="/goal",
        user_id=str(user.id),
    )
    change_snapshot = FeedbackService.build_change_snapshot(db, feedback)
    assert change_snapshot is not None
    assert change_snapshot["changedPaths"] == [
        "/goal",
        "/questions/0/answer",
        "/questions/0/decisionReason",
        "/questions/0/status",
    ]
    assert change_snapshot["fieldChange"] == {
        "jsonPointer": "/goal",
        "before": "验证登录需求",
        "after": "验证登录与账号锁定需求",
    }

    with pytest.raises(AppError) as exc:
        AiTestDesignRevisionService.save_stage_revision(
            db=db,
            record=record,
            stage_key="requirement-analysis",
            base_set_revision_id=edited_set.id,
            expected_set_hash="stale-client-hash",
            items=[edited_payload],
            actor_id=user.id,
        )
    assert exc.value.code == "AI_DESIGN_CONTEXT_CONFLICT"
    assert exc.value.status_code == 409


def test_accept_stage_blocks_unanswered_question_and_resumes_human_gate(db: Session) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-human-gate",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    step = db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    step.status = "SUCCEEDED"
    original_set = worker._materialize_p3_artifact_revision_set(
        db, run, step, _analysis_payload("PENDING")
    )
    gate = AIStepExecution(
        run_id=run.id,
        node_id="requirement_analysis_gate",
        node_type="HUMAN",
        node_name="确认需求分析",
        attempt=1,
        status="WAITING_HUMAN",
    )
    run.status = "WAITING_HUMAN"
    db.add(gate)
    db.flush()

    with pytest.raises(AppError) as exc:
        AiTestDesignRevisionService.accept_stage(
            db=db,
            record=record,
            stage_key="requirement-analysis",
            set_revision_id=original_set.id,
            expected_current_set_revision_id=None,
            decision_snapshot={"answers": {"Q-001": "30 分钟"}},
            actor_id=user.id,
            actor_permissions={"agent.use"},
        )
    assert exc.value.code == "AI_DESIGN_BLOCKING_QUESTIONS"

    edited_set = AiTestDesignRevisionService.save_stage_revision(
        db=db,
        record=record,
        stage_key="requirement-analysis",
        base_set_revision_id=original_set.id,
        expected_set_hash=original_set.set_hash,
        items=[_analysis_payload("ANSWERED")],
        actor_id=user.id,
    )
    accepted = AiTestDesignRevisionService.accept_stage(
        db=db,
        record=record,
        stage_key="requirement-analysis",
        set_revision_id=edited_set.id,
        expected_current_set_revision_id=None,
        decision_snapshot={"answers": {"Q-001": "30 分钟"}},
        actor_id=user.id,
        actor_permissions={"agent.use"},
    )
    assert accepted.current_set_revision_id == edited_set.id
    assert gate.status == "PENDING"
    action = db.query(AIHumanGateAction).filter_by(step_execution_id=gate.id).one()
    assert action.decision_snapshot["acceptedSetRevisionId"] == str(edited_set.id)
    assert action.decision_snapshot["acceptedItems"][0]["questions"][0]["status"] == ("ANSWERED")


@pytest.mark.anyio
async def test_ai_design_record_api_idempotently_creates_and_restores_chain(
    db: Session,
) -> None:
    user, project, task, _requirement = _create_case_design_task(db)

    def override_db():
        yield db

    def override_user() -> User:
        return user

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_runtime_settings] = lambda: AIRuntimeSettings(
        TESTWEAVE_AI_RUNTIME__ENABLED=True
    )

    transport = ASGITransport(app=app)
    base = f"/api/v1/projects/{project.id}/test-tasks/{task.id}/ai-design"
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            f"{base}/records",
            json={"reviewMode": "TRACEABLE"},
            headers={"Idempotency-Key": "record-api-1"},
        )
        assert first.status_code == 202
        assert first.headers["Idempotency-Replay"] == "false"
        record_id = first.json()["id"]

        replay = await client.post(
            f"{base}/records",
            json={"reviewMode": "TRACEABLE"},
            headers={"Idempotency-Key": "record-api-1"},
        )
        assert replay.status_code == 202
        assert replay.headers["Idempotency-Replay"] == "true"
        assert replay.json()["id"] == record_id

        records = await client.get(f"{base}/records")
        assert records.status_code == 200
        assert records.json()["resumeRecordId"] == record_id
        assert len(records.json()["items"]) == 1

        restored = await client.get(
            f"{base}/records/{record_id}",
            params={"stage": "requirement-analysis"},
        )
        assert restored.status_code == 200
        body = restored.json()
        assert body["record"]["id"] == record_id
        assert body["stage"]["artifactType"] == "requirement_analysis@1.0"
        assert body["stage"]["status"] == "GENERATING"
        assert body["source"]["requirement"]["title"] == "登录安全测试需求"


@pytest.mark.anyio
async def test_worker_regeneration_uses_feedback_snapshot_and_rebuilds_candidate_set(
    db: Session,
) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-regeneration",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    generation_step = (
        db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    )
    generation_step.status = "SUCCEEDED"
    source_worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    original_set = source_worker._materialize_p3_artifact_revision_set(
        db, run, generation_step, _analysis_payload("ANSWERED")
    )
    gate_step = AIStepExecution(
        run_id=run.id,
        node_id="requirement_analysis_gate",
        node_type="HUMAN",
        node_name="确认需求分析",
        attempt=1,
        status="WAITING_HUMAN",
    )
    run.status = "WAITING_HUMAN"
    db.add(gate_step)
    db.flush()

    _member, item, revision = SetRevisionService.get_set_revision_members(db, str(original_set.id))[
        0
    ]
    feedback = FeedbackService.create_feedback(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        target_type="ARTIFACT",
        category="遗漏需求",
        comment="补充连续失败计数重置规则",
        target_item_id=str(item.id),
        target_revision_id=str(revision.id),
        user_id=str(user.id),
    )
    request = RegenerationService.create_regeneration_request(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="requirement_analysis",
        target_item_stable_keys=["requirement-analysis"],
        base_set_revision_id=str(original_set.id),
        feedback_ids=[str(feedback.id)],
        idempotency_key="regen-analysis-1",
        requested_by=str(user.id),
    )
    replay = RegenerationService.create_regeneration_request(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="requirement_analysis",
        target_item_stable_keys=["requirement-analysis"],
        base_set_revision_id=str(original_set.id),
        feedback_ids=[str(feedback.id)],
        idempotency_key="regen-analysis-1",
        requested_by=str(user.id),
    )
    assert replay.id == request.id
    second_feedback = FeedbackService.create_feedback(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        target_type="ARTIFACT",
        category="表达模糊",
        comment="改写目标描述",
        target_item_id=str(item.id),
        target_revision_id=str(revision.id),
        user_id=str(user.id),
    )
    with pytest.raises(AppError) as idempotency_conflict:
        RegenerationService.create_regeneration_request(
            db=db,
            project_id=str(project.id),
            run_id=str(run.id),
            node_id="requirement_analysis",
            target_item_stable_keys=["requirement-analysis"],
            base_set_revision_id=str(original_set.id),
            feedback_ids=[str(second_feedback.id)],
            idempotency_key="regen-analysis-1",
            requested_by=str(user.id),
        )
    assert idempotency_conflict.value.code == "REGENERATION_IDEMPOTENCY_CONFLICT"
    db.commit()

    replacement = _analysis_payload("ANSWERED")
    replacement["goal"] = "验证登录、账号锁定与失败计数重置"
    provider = _CapturingRegenerationProvider(replacement)
    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
        custom_provider=provider,
    )

    assert await worker.run_once() is True
    db.expire_all()
    completed_request = db.get(AIRegenerationRequest, request.id)
    assert completed_request is not None
    assert completed_request.status == "COMPLETED"
    assert completed_request.result_set_revision_id is not None
    regenerated_set = db.get(AIArtifactSetRevision, completed_request.result_set_revision_id)
    assert regenerated_set is not None
    assert regenerated_set.review_status == "CANDIDATE"
    assert regenerated_set.base_set_revision_id == original_set.id
    assert original_set.review_status == "SUPERSEDED"
    regenerated_members = SetRevisionService.get_set_revision_members(db, str(regenerated_set.id))
    assert len(regenerated_members) == 1
    assert regenerated_members[0][2].content == replacement
    assert regenerated_members[0][2].source == "REGENERATION"

    assert len(provider.calls) == 1
    provider_input = provider.calls[0]["input"]
    assert provider_input["regenerationRequest"]["feedbackSnapshots"][0]["comment"] == (
        "补充连续失败计数重置规则"
    )
    assert provider_input["regenerationRequest"]["targetItems"][0]["content"] == (
        _analysis_payload("ANSWERED")
    )
    context = db.query(AIContextSnapshot).filter_by(source_regeneration_request_id=request.id).one()
    assert context.purpose == "REGENERATION"

    # 重生成只产生 Candidate，不会自动接受或推进人工门禁。
    assert db.query(AIHumanGateAction).filter_by(step_execution_id=gate_step.id).count() == 0


def test_regeneration_is_blocked_when_target_contains_active_field_lock(
    db: Session,
) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-locked-regeneration",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    step = db.query(AIStepExecution).filter_by(run_id=run.id, node_id="requirement_analysis").one()
    source_worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
    )
    base_set = source_worker._materialize_p3_artifact_revision_set(
        db, run, step, _analysis_payload("ANSWERED")
    )
    _member, item, revision = SetRevisionService.get_set_revision_members(db, str(base_set.id))[0]
    FieldLockService.create_field_lock(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="requirement_analysis",
        artifact_item_id=str(item.id),
        anchor_revision_id=str(revision.id),
        json_pointer="/goal",
        user_id=str(user.id),
    )

    with pytest.raises(AppError) as exc:
        RegenerationService.create_regeneration_request(
            db=db,
            project_id=str(project.id),
            run_id=str(run.id),
            node_id="requirement_analysis",
            target_item_stable_keys=[item.stable_key],
            base_set_revision_id=str(base_set.id),
            idempotency_key="regen-locked-1",
            requested_by=str(user.id),
        )
    assert exc.value.code == "REGENERATION_BLOCKED_BY_LOCK"


@pytest.mark.anyio
async def test_four_stage_workflow_persists_independent_revisions_and_human_gates(
    db: Session,
) -> None:
    user, project, task, _requirement = _create_case_design_task(db)
    record, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=user.id,
        actor_permissions={"agent.use"},
        idempotency_key="ai-design-four-stage-e2e",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    worker = AIRuntimeWorker(
        db,
        AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake"),
        custom_provider=_FourStageProvider(),
    )

    async def execute_generation_and_gate() -> None:
        assert await worker.run_once() is True
        assert await worker.run_once() is True

    def latest_set(node_id: str) -> AIArtifactSetRevision:
        result = (
            db.query(AIArtifactSetRevision)
            .filter_by(run_id=record.run_id, producer_node_id=node_id)
            .order_by(AIArtifactSetRevision.set_revision_no.desc())
            .first()
        )
        assert result is not None
        return result

    async def accept_and_execute_gate(
        stage_key: str,
        set_revision: AIArtifactSetRevision,
        decision_snapshot: dict,
    ) -> None:
        AiTestDesignRevisionService.accept_stage(
            db=db,
            record=record,
            stage_key=stage_key,
            set_revision_id=set_revision.id,
            expected_current_set_revision_id=None,
            decision_snapshot=decision_snapshot,
            actor_id=user.id,
            actor_permissions={"agent.use"},
        )
        assert await worker.run_once() is True

    # 需求分析生成后必须停在人工门禁；回答问题通过新 Revision 保存。
    await execute_generation_and_gate()
    analysis_state = AiTestDesignQueryService.get_workbench_state(
        db, record, "requirement-analysis"
    )
    assert analysis_state["stage"]["status"] == "WAITING_HUMAN"
    analysis_candidate = latest_set("requirement_analysis")
    answered_analysis = AiTestDesignRevisionService.save_stage_revision(
        db=db,
        record=record,
        stage_key="requirement-analysis",
        base_set_revision_id=analysis_candidate.id,
        expected_set_hash=analysis_candidate.set_hash,
        items=[_analysis_payload("ANSWERED")],
        actor_id=user.id,
    )
    await accept_and_execute_gate(
        "requirement-analysis",
        answered_analysis,
        {"questions": [{"id": "Q-001", "status": "ANSWERED"}]},
    )

    # 测试点生成后只把人工选中的点送入下一阶段。
    await execute_generation_and_gate()
    points_candidate = latest_set("test_points")
    await accept_and_execute_gate(
        "test-points",
        points_candidate,
        {"selectedTestPointKeys": ["TP-001"]},
    )

    # 用例候选也必须人工接受，不能由生成者自动发布。
    await execute_generation_and_gate()
    cases_candidate = latest_set("test_cases")
    assert cases_candidate.review_status == "CANDIDATE"
    await accept_and_execute_gate(
        "test-cases",
        cases_candidate,
        {"acceptedCaseKeys": ["TC-001"]},
    )

    # Finding 未决时仍停在人审；处理后保存独立评审 Revision。
    await execute_generation_and_gate()
    review_candidate = latest_set("case_review")
    review_content = SetRevisionService.get_set_revision_members(db, str(review_candidate.id))[0][
        2
    ].content.copy()
    review_content["findings"] = [
        {
            **review_content["findings"][0],
            "decision": "ACCEPTED",
            "decisionReason": "已转为定向修订请求",
        }
    ]
    review_content["revisionRequests"] = [
        {
            "id": "RR-F-001",
            "caseRef": "TC-001",
            "fieldPath": "/steps/0/expected",
            "instruction": "补充服务端失败计数观察点",
            "status": "CONFIRMED",
        }
    ]
    review_edited = AiTestDesignRevisionService.save_stage_revision(
        db=db,
        record=record,
        stage_key="case-review",
        base_set_revision_id=review_candidate.id,
        expected_set_hash=review_candidate.set_hash,
        items=[review_content],
        actor_id=user.id,
    )
    await accept_and_execute_gate(
        "case-review",
        review_edited,
        {"findingDecisions": [{"stableKey": "F-001", "decision": "ACCEPTED"}]},
    )

    db.expire_all()
    run = db.get(AICapabilityRun, record.run_id)
    assert run is not None
    assert run.status == "SUCCEEDED"
    accepted_nodes = {
        pointer.node_id
        for pointer in db.query(AICurrentAcceptedRevisionSet).filter_by(run_id=record.run_id).all()
    }
    assert accepted_nodes == {
        "requirement_analysis",
        "test_points",
        "test_cases",
        "case_review",
    }
    persisted_review = db.get(AIArtifactSetRevision, review_edited.id)
    assert persisted_review is not None
    assert persisted_review.decision_snapshot == {
        "findingDecisions": [{"stableKey": "F-001", "decision": "ACCEPTED"}]
    }
    assert db.query(AIDependencyEdge).filter_by(run_id=record.run_id).count() == 6
    summaries = AiTestDesignQueryService.summarize_record(db, record)["stages"]
    assert [stage["status"] for stage in summaries] == [
        "ACCEPTED",
        "ACCEPTED",
        "ACCEPTED",
        "ACCEPTED",
    ]


def test_runtime_and_provider_settings_load_real_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_AI_RUNTIME__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_AI_PROVIDER__TYPE", "openai_compatible")
    monkeypatch.setenv("TESTWEAVE_AI_PROVIDER__BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("TESTWEAVE_AI_PROVIDER__API_KEY", "test-only-key")
    monkeypatch.setenv("TESTWEAVE_AI_PROVIDER__QUALITY_MODEL", "quality-model")

    runtime = AIRuntimeSettings()
    provider = AIProviderSettings()

    assert runtime.enabled is True
    assert provider.is_configured() is True
    assert provider.quality_model == "quality-model"

    with pytest.raises(ValueError, match="禁止使用 Fake"):
        AIProviderSettings(TESTWEAVE_AI_PROVIDER__TYPE="fake").validate_for_production(
            is_production=True
        )
