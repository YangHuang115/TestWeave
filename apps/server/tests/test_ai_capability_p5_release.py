import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityDeployment,
    AICapabilityVersion,
    Base,
    Project,
)
from testweave.modules.ai_capabilities.release_service import (
    ReleasePolicyProvider,
    ReleaseResolver,
    ReleaseService,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(bind=engine)


def test_release_policy_provider_returns_no_configured_quality_rules(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Proj", key="P5", owner_id=uuid.uuid4())
    db.add(proj)
    db.flush()

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Test Cap",
        code="TEST_CAP",
        category="TEST_DESIGN",
    )
    db.add(cap)
    db.flush()

    cand_v = AICapabilityVersion(
        id=uuid.uuid4(),
        capability_id=cap.id,
        version="1.1.0",
        package_fingerprint="fp123",
        status="SYNCED_DRAFT",
    )
    db.add(cand_v)
    db.commit()

    res = ReleasePolicyProvider.evaluate_release_policy(
        db, cap, cand_v, base_version=None, evaluation_run=None, comparison=None
    )

    assert res["policy_status"] == "NO_CONFIGURED_QUALITY_RULES"
    assert res["blocking_checks"] == []
    assert len(res["advisories"]) >= 1  # EVALUATION_NOT_COMPLETED advisory


def test_canary_routing_distribution_and_salt_stability(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Proj", key="P5", owner_id=uuid.uuid4())
    db.add(proj)

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Test Cap",
        code="TEST_CAP",
        category="TEST_DESIGN",
    )
    db.add(cap)
    db.flush()

    v1 = AICapabilityVersion(
        id=uuid.uuid4(), capability_id=cap.id, version="1.0.0", package_fingerprint="fp1"
    )
    v2 = AICapabilityVersion(
        id=uuid.uuid4(), capability_id=cap.id, version="2.0.0", package_fingerprint="fp2"
    )
    db.add_all([v1, v2])
    db.flush()

    deploy = AICapabilityDeployment(
        id=uuid.uuid4(),
        project_id=proj.id,
        capability_id=cap.id,
        stable_version_id=v1.id,
        canary_version_id=v2.id,
        canary_basis_points=5000,  # 50%
        routing_salt="fixed-salt-12345",
        deployment_revision=1,
        row_version=1,
        status="ACTIVE",
    )
    db.add(deploy)
    db.commit()

    # 重复调用的分桶绝对稳定
    _d1, ver1, info1 = ReleaseResolver.resolve_run_deployment(
        db, str(cap.id), routing_subject="user-A"
    )
    _d2, ver2, info2 = ReleaseResolver.resolve_run_deployment(
        db, str(cap.id), routing_subject="user-A"
    )

    assert info1["bucket"] == info2["bucket"]
    assert ver1.id == ver2.id


def test_rollback_requires_historically_released_version(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Proj", key="P5", owner_id=uuid.uuid4())
    db.add(proj)

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Test Cap",
        code="TEST_CAP",
        category="TEST_DESIGN",
    )
    db.add(cap)
    db.flush()

    v1 = AICapabilityVersion(
        id=uuid.uuid4(), capability_id=cap.id, version="1.0.0", package_fingerprint="fp1"
    )
    v2_unreleased = AICapabilityVersion(
        id=uuid.uuid4(), capability_id=cap.id, version="2.0.0", package_fingerprint="fp2"
    )
    db.add_all([v1, v2_unreleased])
    db.flush()

    deploy = AICapabilityDeployment(
        id=uuid.uuid4(),
        project_id=proj.id,
        capability_id=cap.id,
        stable_version_id=v1.id,
        routing_salt="salt-123",
        deployment_revision=1,
    )
    db.add(deploy)
    db.commit()

    # 尝试回滚到从未发布过的 v2_unreleased 必须报错
    with pytest.raises(AppError) as exc_info:
        ReleaseService.rollback(
            db=db,
            capability_id=str(cap.id),
            target_version_id=str(v2_unreleased.id),
            reason="Illegal rollback target",
            expected_deployment_revision=1,
        )
    assert exc_info.value.code == "INELIGIBLE_ROLLBACK_TARGET"
