import uuid

import pytest
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import AICapabilityRun, Project, User
from testweave.modules.ai_capability.revision import (
    AcceptanceService,
    ArtifactService,
    DiffService,
    FieldLockService,
    SetRevisionService,
)


@pytest.fixture
def p3_test_context(db: Session) -> dict:
    user = User(
        username="p3tester",
        email="p3@testweave.com",
        display_name="P3 Tester",
        hashed_password="pwd",
    )
    db.add(user)
    db.flush()

    project = Project(
        key="P3PROJ",
        name="P3 Project",
        owner_id=user.id,
    )
    db.add(project)
    db.flush()

    run = AICapabilityRun(
        capability_version_id=uuid.uuid4(),
        project_id=project.id,
        initiator_id=user.id,
        trace_id=f"trace-p3-{uuid.uuid4().hex[:8]}",
        status="RUNNING",
        input_snapshot={"test": "data"},
        execution_snapshot={"workflow": {}},
    )
    db.add(run)
    db.commit()

    return {"user": user, "project": project, "run": run}


def test_artifact_and_set_revision_lifecycle(db: Session, p3_test_context: dict) -> None:
    proj = p3_test_context["project"]
    run = p3_test_context["run"]
    user = p3_test_context["user"]

    # 物化 10 条测试点条目与初始 Revision
    items_and_revs = []
    for i in range(1, 11):
        item = ArtifactService.get_or_create_artifact_item(
            db=db,
            project_id=str(proj.id),
            run_id=str(run.id),
            producer_node_id="node_test_design",
            artifact_type="TEST_POINT",
            stable_key=f"TP-{i:02d}",
            created_by=str(user.id),
        )

        rev = ArtifactService.create_artifact_revision(
            db=db,
            project_id=str(proj.id),
            artifact_item_id=str(item.id),
            content={"title": f"测试点 {i:02d}", "priority": "HIGH"},
            source="INITIAL_GENERATION",
            created_by=str(user.id),
        )
        items_and_revs.append((item, rev))

    # 构建 Candidate SetRevision S1
    set_s1 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(proj.id),
        run_id=str(run.id),
        producer_node_id="node_test_design",
        input_fingerprint="fp-s1",
        items_and_revisions=items_and_revs,
        review_status="CANDIDATE",
        validation_status="VALID",
    )

    assert set_s1.set_revision_no == 1
    assert set_s1.item_count == 10
    assert set_s1.review_status == "CANDIDATE"

    # 接受 Set S1
    acc_ptr = AcceptanceService.accept_set_revision(db, str(set_s1.id), user_id=str(user.id))
    assert acc_ptr.current_set_revision_id == set_s1.id
    assert acc_ptr.freshness_status == "CURRENT"


def test_field_lock_and_conflict_detection(db: Session, p3_test_context: dict) -> None:
    proj = p3_test_context["project"]
    run = p3_test_context["run"]
    user = p3_test_context["user"]

    item = ArtifactService.get_or_create_artifact_item(
        db=db,
        project_id=str(proj.id),
        run_id=str(run.id),
        producer_node_id="node_1",
        artifact_type="TEST_POINT",
        stable_key="TP-L1",
    )

    rev1 = ArtifactService.create_artifact_revision(
        db=db,
        project_id=str(proj.id),
        artifact_item_id=str(item.id),
        content={"title": "锁定测试", "sub": {"field_a": "value_a"}},
        source="INITIAL_GENERATION",
    )

    # 锁定 /sub/field_a
    lock = FieldLockService.create_field_lock(
        db=db,
        project_id=str(proj.id),
        run_id=str(run.id),
        node_id="node_1",
        artifact_item_id=str(item.id),
        anchor_revision_id=str(rev1.id),
        json_pointer="/sub/field_a",
        user_id=str(user.id),
    )
    assert lock.status == "ACTIVE"

    # 再次创建重叠锁必须触发 LOCK_OVERLAP
    with pytest.raises(AppError) as exc_overlap:
        FieldLockService.create_field_lock(
            db=db,
            project_id=str(proj.id),
            run_id=str(run.id),
            node_id="node_1",
            artifact_item_id=str(item.id),
            anchor_revision_id=str(rev1.id),
            json_pointer="/sub/field_a",
            user_id=str(user.id),
        )
    assert exc_overlap.value.code == "LOCK_OVERLAP"

    # 尝试将 /sub/field_a 的值修改为 value_b，校验必须抛出 LOCK_CONFLICT
    rev2_bad = ArtifactService.create_artifact_revision(
        db=db,
        project_id=str(proj.id),
        artifact_item_id=str(item.id),
        content={"title": "锁定测试", "sub": {"field_a": "value_b"}},
        source="USER_EDIT",
    )

    with pytest.raises(AppError) as exc_conflict:
        FieldLockService.verify_field_locks_for_items(db, [(item, rev2_bad)])
    assert exc_conflict.value.code == "LOCK_CONFLICT"


def test_diff_service_compare_sets(db: Session, p3_test_context: dict) -> None:
    proj = p3_test_context["project"]
    run = p3_test_context["run"]

    items_and_revs_s1 = []
    items_and_revs_s2 = []

    # 模拟 10 条中 3 条保持不变、7 条发生变化
    for i in range(1, 11):
        item = ArtifactService.get_or_create_artifact_item(
            db=db,
            project_id=str(proj.id),
            run_id=str(run.id),
            producer_node_id="node_1",
            artifact_type="TEST_POINT",
            stable_key=f"TP-D{i:02d}",
        )
        rev1 = ArtifactService.create_artifact_revision(
            db=db,
            project_id=str(proj.id),
            artifact_item_id=str(item.id),
            content={"title": f"原始测试点 {i:02d}"},
            source="INITIAL_GENERATION",
        )
        items_and_revs_s1.append((item, rev1))

        if i <= 3:
            # 3 条保持原 Revision
            items_and_revs_s2.append((item, rev1))
        else:
            # 7 条产生新 Revision
            rev2 = ArtifactService.create_artifact_revision(
                db=db,
                project_id=str(proj.id),
                artifact_item_id=str(item.id),
                content={"title": f"重生成测试点 {i:02d}"},
                source="REGENERATION",
                parent_revision_ids=[str(rev1.id)],
            )
            items_and_revs_s2.append((item, rev2))

    set_s1 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(proj.id),
        run_id=str(run.id),
        producer_node_id="node_1",
        input_fingerprint="fp1",
        items_and_revisions=items_and_revs_s1,
    )

    set_s2 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(proj.id),
        run_id=str(run.id),
        producer_node_id="node_1",
        input_fingerprint="fp2",
        items_and_revisions=items_and_revs_s2,
    )

    diff = DiffService.compare_set_revisions(db, str(set_s1.id), str(set_s2.id))
    summary = diff["summary"]

    assert summary["total_items"] == 10
    assert summary["unchanged_count"] == 3
    assert summary["modified_count"] == 7
    assert summary["added_count"] == 0
    assert summary["removed_count"] == 0
