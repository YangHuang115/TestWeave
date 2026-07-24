import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapability,
    AICapabilityVersion,
    AIEvaluationCaseRecommendation,
    AIEvaluationSet,
    AIFeedback,
    Base,
    Project,
)
from testweave.modules.ai_capabilities.evaluation_service import EvaluationService
from testweave.modules.ai_capabilities.package_service import PackageService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(bind=engine)


def test_recommendation_acceptance_creates_project_case_revision(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Eval Proj", key="P5E", owner_id=uuid.uuid4())
    db.add(proj)
    db.flush()

    rec = AIEvaluationCaseRecommendation(
        id=uuid.uuid4(),
        project_id=proj.id,
        source_type="FEEDBACK",
        source_id="fb-101",
        suggested_inputs_json={"prompt": "Sensitive data original"},
        status="PROPOSED",
    )
    db.add(rec)
    db.flush()

    case_rev = EvaluationService.accept_recommendation(
        db=db,
        recommendation_id=str(rec.id),
        case_name="Redacted Case 1",
        redacted_inputs={"prompt": "Redacted prompt data"},
        declarative_assertions=[{"type": "contains", "value": "expected"}],
    )

    assert case_rev is not None
    assert case_rev.sensitivity == "REDACTED"
    assert rec.status == "ACCEPTED"
    assert rec.accepted_case_revision_id == case_rev.id


def test_create_comparison_not_comparable_when_set_mismatch(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Eval Proj", key="P5E", owner_id=uuid.uuid4())
    db.add(proj)

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Cap",
        code="CAP",
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

    set1 = AIEvaluationSet(
        id=uuid.uuid4(), project_id=proj.id, scope_type="PROJECT", set_key="set-1", name="Set 1"
    )
    set2 = AIEvaluationSet(
        id=uuid.uuid4(), project_id=proj.id, scope_type="PROJECT", set_key="set-2", name="Set 2"
    )
    db.add_all([set1, set2])
    db.flush()

    srev1 = EvaluationService.create_evaluation_set_revision(db, str(set1.id), [])
    srev2 = EvaluationService.create_evaluation_set_revision(db, str(set2.id), [])

    run1 = EvaluationService.create_evaluation_run(db, str(cap.id), str(v1.id), str(srev1.id))
    run2 = EvaluationService.create_evaluation_run(db, str(cap.id), str(v2.id), str(srev2.id))

    run1.status = "COMPLETED"
    run2.status = "COMPLETED"
    db.flush()

    comp = EvaluationService.create_comparison(db, str(run1.id), str(run2.id))

    assert comp.status == "NOT_COMPARABLE"
    assert comp.not_comparable_reason == "SET_REVISION_MISMATCH"


def test_workspace_package_creation_and_hash(db: Session) -> None:
    proj = Project(id=uuid.uuid4(), name="P5 Package Proj", key="P5P", owner_id=uuid.uuid4())
    db.add(proj)

    cap = AICapability(
        id=uuid.uuid4(),
        project_id=proj.id,
        scope="PROJECT",
        namespace="default",
        name="Cap",
        code="CAP",
        category="TEST_DESIGN",
    )
    db.add(cap)
    db.flush()

    fb = AIFeedback(
        id=uuid.uuid4(),
        project_id=proj.id,
        run_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        target_type="CAPABILITY",
        category="DISLIKE",
        comment="Bad output",
    )
    db.add(fb)
    db.flush()

    suggs = PackageService.generate_suggestions_from_evidence(db, str(cap.id), str(proj.id))
    assert len(suggs) == 1

    pkg = PackageService.create_workspace_package(
        db,
        capability_id=str(cap.id),
        package_type="OPTIMIZATION",
        suggestion_ids=[str(suggs[0].id)],
    )

    assert pkg is not None
    assert pkg.status == "READY"
    assert len(pkg.package_hash) == 64
    assert suggs[0].status == "PACKAGED"
