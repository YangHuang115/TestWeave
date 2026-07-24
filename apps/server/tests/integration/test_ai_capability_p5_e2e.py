import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityReleaseAction,
    AICapabilityVersion,
    AIEvaluationCaseRecommendation,
    AIEvaluationSet,
    AIFeedback,
    Base,
    Project,
    User,
)
from testweave.modules.ai_capabilities.evaluation_service import EvaluationService
from testweave.modules.ai_capabilities.package_service import PackageService
from testweave.modules.ai_capabilities.release_service import ReleaseResolver, ReleaseService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(bind=engine)


def test_p5_full_lifecycle_end_to_end(db: Session) -> None:
    # 1. 基础项目、能力与 V1
    user = User(
        id=uuid.uuid4(),
        username="admin_p5",
        email="admin@testweave.local",
        display_name="Admin",
        hashed_password="hash",
        is_system_admin=True,
    )
    proj = Project(id=uuid.uuid4(), name="P5 E2E Proj", key="P5E2E", owner_id=user.id)
    db.add_all([user, proj])
    db.flush()

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Design Agent",
        code="DESIGN_AGENT",
        category="TEST_DESIGN",
    )
    db.add(cap)
    db.flush()

    v1 = AICapabilityVersion(
        id=uuid.uuid4(),
        capability_id=cap.id,
        version="1.0.0",
        package_fingerprint="fp-v1",
        status="PUBLISHED",
    )
    db.add(v1)
    db.flush()

    cap.current_published_version_id = v1.id
    ReleaseService.ensure_deployment_exists(db, str(cap.id), v1.id)

    # 2. 从 Feedback 生产观察产生 Recommendation
    fb = AIFeedback(
        id=uuid.uuid4(),
        project_id=proj.id,
        run_id=uuid.uuid4(),
        created_by=user.id,
        target_type="CAPABILITY",
        category="DISLIKE",
        comment="Original raw feedback",
    )
    rec = AIEvaluationCaseRecommendation(
        id=uuid.uuid4(),
        project_id=proj.id,
        source_type="FEEDBACK",
        source_id=str(fb.id),
        suggested_inputs_json={"raw_prompt": "Sensitive prompt info"},
        status="PROPOSED",
    )
    db.add_all([fb, rec])
    db.flush()

    # 3. 人工脱敏与接受
    case_rev = EvaluationService.accept_recommendation(
        db,
        str(rec.id),
        "Redacted Case 101",
        redacted_inputs={"prompt": "Sanitized prompt"},
        declarative_assertions=[{"type": "non_empty"}],
    )
    assert case_rev.sensitivity == "REDACTED"
    assert rec.status == "ACCEPTED"

    # 4. 冻结评测集 Revision
    eval_set = AIEvaluationSet(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope_type="PROJECT",
        set_key="p5-reg-set",
        name="P5 Regression Set",
    )
    db.add(eval_set)
    db.flush()

    srev = EvaluationService.create_evaluation_set_revision(
        db, str(eval_set.id), [str(case_rev.id)]
    )
    assert srev.revision_no == 1

    # 5. 候选 V2 版本同集评测
    v2 = AICapabilityVersion(
        id=uuid.uuid4(),
        capability_id=cap.id,
        version="2.0.0",
        package_fingerprint="fp-v2",
        status="SYNCED_DRAFT",
    )
    db.add(v2)
    db.flush()

    eval_run_v1 = EvaluationService.create_evaluation_run(db, str(cap.id), str(v1.id), str(srev.id))
    eval_run_v2 = EvaluationService.create_evaluation_run(db, str(cap.id), str(v2.id), str(srev.id))

    eval_run_v1.status = "COMPLETED"
    eval_run_v2.status = "COMPLETED"
    db.flush()

    # 6. 生成 Comparison
    comp = EvaluationService.create_comparison(db, str(eval_run_v1.id), str(eval_run_v2.id))
    assert comp.status == "READY"

    # 7. 基于 Evidence 生成 Suggestion
    suggs = PackageService.generate_suggestions_from_evidence(db, str(cap.id), str(proj.id))
    assert len(suggs) >= 1

    # 8. 用户导出不可变 Workspace Package
    pkg = PackageService.create_workspace_package(
        db, str(cap.id), "OPTIMIZATION", suggestion_ids=[str(suggs[0].id)]
    )
    assert pkg.status == "READY"
    assert len(pkg.package_hash) == 64

    # 9. 创建 ReleaseRequest
    rel_req = ReleaseService.create_release_request(
        db,
        str(proj.id),
        str(cap.id),
        str(v2.id),
        str(eval_run_v2.id),
        str(comp.id),
        reason="Publishing V2",
    )
    assert rel_req.status == "APPROVED"
    assert rel_req.policy_provider_snapshot_json["policy_status"] == "NO_CONFIGURED_QUALITY_RULES"

    # 10. 开启 10% 灰度
    deploy_canary = ReleaseService.start_canary(
        db, str(rel_req.id), canary_basis_points=1000, reason="10% Canary"
    )
    assert deploy_canary.canary_version_id == v2.id

    # 11. 校验 Canary 分桶稳定性
    _, run_ver, routing1 = ReleaseResolver.resolve_run_deployment(
        db, str(cap.id), routing_subject="user-123"
    )
    _, run_ver_repeat, routing2 = ReleaseResolver.resolve_run_deployment(
        db, str(cap.id), routing_subject="user-123"
    )
    assert routing1["bucket"] == routing2["bucket"]
    assert run_ver.id == run_ver_repeat.id

    # 12. 调整灰度为 25% (保持 salt 不变)
    old_salt = deploy_canary.routing_salt
    deploy_adj = ReleaseService.adjust_canary(
        db,
        str(deploy_canary.id),
        canary_basis_points=2500,
        reason="Adjust to 25%",
        expected_deployment_revision=deploy_canary.deployment_revision,
    )
    assert deploy_adj.routing_salt == old_salt

    # 13. 全量晋级 Promote
    deploy_promoted = ReleaseService.promote(
        db,
        str(deploy_adj.id),
        reason="Promote to V2 Stable",
        expected_deployment_revision=deploy_adj.deployment_revision,
    )
    assert deploy_promoted.stable_version_id == v2.id
    assert deploy_promoted.canary_version_id is None
    assert cap.current_published_version_id == v2.id

    # 14. 显式回滚至 V1
    deploy_rolled_back = ReleaseService.rollback(
        db,
        str(cap.id),
        target_version_id=str(v1.id),
        reason="Critical bug in V2",
        expected_deployment_revision=deploy_promoted.deployment_revision,
    )
    assert deploy_rolled_back.stable_version_id == v1.id
    assert cap.current_published_version_id == v1.id

    # 15. 校验 Audit/Release Action 历史均完整留存
    stmt_actions = select(AICapabilityReleaseAction).where(
        AICapabilityReleaseAction.capability_id == cap.id
    )
    actions = db.scalars(stmt_actions).all()
    action_types = [a.action_type for a in actions]
    assert "FULL_RELEASE" in action_types
    assert "START_CANARY" in action_types
    assert "ADJUST_CANARY" in action_types
    assert "ROLLBACK" in action_types
