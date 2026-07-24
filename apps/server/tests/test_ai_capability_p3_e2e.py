import uuid

from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
    Project,
    User,
)
from testweave.modules.ai_capability.revision import (
    AcceptanceService,
    ArtifactService,
    ContextService,
    DependencyService,
    DiffService,
    FeedbackService,
    FieldLockService,
    RegenerationService,
    SetRevisionService,
)


def test_full_10_test_points_regeneration_loop_e2e(db: Session) -> None:
    # 1. 初始化测试用户与 Run
    user = User(
        username="e2etester",
        email="e2e@testweave.com",
        display_name="E2E Tester",
        hashed_password="pwd",
    )
    db.add(user)
    db.flush()

    project = Project(key="E2EPROJ", name="E2E Project", owner_id=user.id)
    db.add(project)
    db.flush()

    run = AICapabilityRun(
        capability_version_id=uuid.uuid4(),
        project_id=project.id,
        initiator_id=user.id,
        trace_id=f"trace-e2e-{uuid.uuid4().hex[:8]}",
        status="RUNNING",
        input_snapshot={"req_id": "REQ-10006"},
        execution_snapshot={"workflow": {"node_test_design": ["node_case_gen"]}},
    )
    db.add(run)
    db.commit()

    # 2. 初始生成 10 条测试点并物化 S1 Candidate
    items_and_revs_s1 = []
    for i in range(1, 11):
        item = ArtifactService.get_or_create_artifact_item(
            db=db,
            project_id=str(project.id),
            run_id=str(run.id),
            producer_node_id="node_test_design",
            artifact_type="TEST_POINT",
            stable_key=f"TP-E2E-{i:02d}",
            created_by=str(user.id),
        )
        rev = ArtifactService.create_artifact_revision(
            db=db,
            project_id=str(project.id),
            artifact_item_id=str(item.id),
            content={"title": f"初始测试点 {i:02d}", "status": "DRAFT"},
            source="INITIAL_GENERATION",
            created_by=str(user.id),
        )
        items_and_revs_s1.append((item, rev))

    set_s1 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        producer_node_id="node_test_design",
        input_fingerprint="fp-s1",
        items_and_revisions=items_and_revs_s1,
        review_status="CANDIDATE",
        validation_status="VALID",
    )
    assert set_s1.item_count == 10

    # 3. 接受初始集合 S1 (转换为 Golden Accepted State)
    workflow_dag = {"node_test_design": ["node_case_gen"]}
    acc_s1 = AcceptanceService.accept_set_revision(
        db=db,
        set_revision_id=str(set_s1.id),
        user_id=str(user.id),
        workflow_dag=workflow_dag,
    )
    assert acc_s1.current_set_revision_id == set_s1.id

    # 4. 物化下游 node_case_gen 的 ContextSnapshot 并进行首次执行消费
    ctx1 = ContextService.materialize_context_snapshot(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="node_case_gen",
        purpose="STEP_EXECUTION",
        capability_version_id=str(run.capability_version_id),
        package_fingerprint="pkg-fp",
        execution_snapshot_hash="snap-hash",
        node_config={},
        run_input=run.input_snapshot,
        upstream_node_ids=["node_test_design"],
    )
    # 下游上下文读取到了完整 10 条测试点
    assert len(ctx1.content["upstream_data"]["node_test_design"]) == 10

    # 记录消费依赖边
    DependencyService.record_dependency_edge(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        upstream_node_id="node_test_design",
        upstream_set_revision_id=str(set_s1.id),
        downstream_node_id="node_case_gen",
        downstream_context_snapshot_id=str(ctx1.id),
    )

    # 假设下游 node_case_gen 也产生并接受了初始 OutputSet C1
    item_down = ArtifactService.get_or_create_artifact_item(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        producer_node_id="node_case_gen",
        artifact_type="CASE",
        stable_key="TC-01",
    )
    rev_down = ArtifactService.create_artifact_revision(
        db=db,
        project_id=str(project.id),
        artifact_item_id=str(item_down.id),
        content={"name": "用例1"},
        source="INITIAL_GENERATION",
    )
    set_c1 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        producer_node_id="node_case_gen",
        input_fingerprint="fp-c1",
        items_and_revisions=[(item_down, rev_down)],
    )
    AcceptanceService.accept_set_revision(db, str(set_c1.id), user_id=str(user.id))

    # 5. 锁定其中 3 条 (TP-E2E-01, 02, 03)
    for i in range(1, 4):
        item, rev = items_and_revs_s1[i - 1]
        FieldLockService.create_field_lock(
            db=db,
            project_id=str(project.id),
            run_id=str(run.id),
            node_id="node_test_design",
            artifact_item_id=str(item.id),
            anchor_revision_id=str(rev.id),
            json_pointer="/title",
            user_id=str(user.id),
        )

    # 6. 对另外 7 条 (TP-E2E-04 ~ 10) 创建 Feedback
    feedback_ids = []
    for i in range(4, 11):
        item, rev = items_and_revs_s1[i - 1]
        fb = FeedbackService.create_feedback(
            db=db,
            project_id=str(project.id),
            run_id=str(run.id),
            target_type="FIELD",
            target_item_id=str(item.id),
            target_revision_id=str(rev.id),
            json_pointer="/status",
            category="CORRECTION_SUGGESTION",
            comment=f"建议修改第 {i} 条测试点描述",
            user_id=str(user.id),
        )
        feedback_ids.append(str(fb.id))

    # 7. 发起局部重生成请求 (目标为 7 条)
    target_7_keys = [f"TP-E2E-{i:02d}" for i in range(4, 11)]
    regen_req = RegenerationService.create_regeneration_request(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="node_test_design",
        target_item_stable_keys=target_7_keys,
        base_set_revision_id=str(set_s1.id),
        feedback_ids=feedback_ids,
        requested_by=str(user.id),
    )
    assert regen_req.status == "PENDING"

    # 8. Provider 仅仅返回 7 条 replacement
    replacements_7 = [
        {
            "targetRef": f"target-TP-E2E-{i:02d}",
            "title": f"优化后的测试点 {i:02d}",
            "status": "REFINED",
        }
        for i in range(4, 11)
    ]

    # 9. 服务端重构出完整 10 条候选集合 S2
    set_s2 = RegenerationService.process_regeneration_response(
        db=db,
        regeneration_request_id=str(regen_req.id),
        replacements=replacements_7,
        capability_version_id=str(run.capability_version_id),
        package_fingerprint="pkg-fp",
        execution_snapshot_hash="snap-hash",
        node_config={},
        run_input=run.input_snapshot,
    )
    assert set_s2.item_count == 10
    assert set_s2.set_revision_no == 2
    assert set_s2.review_status == "CANDIDATE"

    # 10. Diff 对比显示 3 条保持不变、7 条发生变化
    diff_res = DiffService.compare_set_revisions(db, str(set_s1.id), str(set_s2.id))
    assert diff_res["summary"]["unchanged_count"] == 3
    assert diff_res["summary"]["modified_count"] == 7

    # 11. 接受新集合 S2 -> 下游自动触发 STALE 传播
    acc_s2 = AcceptanceService.accept_set_revision(
        db=db,
        set_revision_id=str(set_s2.id),
        user_id=str(user.id),
        workflow_dag=workflow_dag,
    )
    assert acc_s2.current_set_revision_id == set_s2.id

    # 检查下游 node_case_gen 的 CurrentAcceptedSet 变为了 STALE 且 rerun_required=True
    down_acc = (
        db.query(AICurrentAcceptedRevisionSet)
        .filter_by(run_id=run.id, node_id="node_case_gen")
        .first()
    )
    assert down_acc is not None
    assert down_acc.freshness_status == "STALE"
    assert down_acc.rerun_required is True

    # 12. 重跑下游：重新物化 ContextSnapshot 并确认包含完整 10 条而不是 7 条 Patch
    ctx2 = ContextService.materialize_context_snapshot(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        node_id="node_case_gen",
        purpose="STEP_EXECUTION",
        capability_version_id=str(run.capability_version_id),
        package_fingerprint="pkg-fp",
        execution_snapshot_hash="snap-hash",
        node_config={},
        run_input=run.input_snapshot,
        upstream_node_ids=["node_test_design"],
    )

    upstream_data_10 = ctx2.content["upstream_data"]["node_test_design"]
    assert len(upstream_data_10) == 10
    # 前 3 条保留初始标题，后 7 条变更为优化后的标题
    assert upstream_data_10[0]["title"] == "初始测试点 01"
    assert upstream_data_10[3]["title"] == "优化后的测试点 04"

    # 下游重新接受新集合 C2，恢复 CURRENT 状态
    item_down2, rev_down2 = (
        item_down,
        ArtifactService.create_artifact_revision(
            db=db,
            project_id=str(project.id),
            artifact_item_id=str(item_down.id),
            content={"name": "用例1更新"},
            source="REGENERATION",
        ),
    )
    set_c2 = SetRevisionService.construct_artifact_set_revision(
        db=db,
        project_id=str(project.id),
        run_id=str(run.id),
        producer_node_id="node_case_gen",
        input_fingerprint="fp-c2",
        items_and_revisions=[(item_down2, rev_down2)],
    )
    AcceptanceService.accept_set_revision(db, str(set_c2.id), user_id=str(user.id))

    down_acc_after = (
        db.query(AICurrentAcceptedRevisionSet)
        .filter_by(run_id=run.id, node_id="node_case_gen")
        .first()
    )
    assert down_acc_after.freshness_status == "CURRENT"
    assert down_acc_after.rerun_required is False
