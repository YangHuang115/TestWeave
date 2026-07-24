import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityVersion,
    AIEvaluationCase,
    AIEvaluationCaseRecommendation,
    AIEvaluationCaseRevision,
    AIEvaluationComparison,
    AIEvaluationComparisonItem,
    AIEvaluationResult,
    AIEvaluationRun,
    AIEvaluationSet,
    AIEvaluationSetRevision,
    AIEvaluationSetRevisionCase,
)
from testweave.modules.ai_capabilities.p5_helpers import compute_canonical_json_hash
from testweave.modules.audit.service import AuditService


class EvaluationService:
    """AI 能力评测、案例推荐与逐案例比对核心服务。"""

    # =========================================================================
    # 1. 案例推荐与审核脱敏
    # =========================================================================

    @staticmethod
    def accept_recommendation(
        db: Session,
        recommendation_id: str,
        case_name: str,
        redacted_inputs: dict[str, Any],
        declarative_assertions: list[Any],
        human_decision_fixture: dict[str, Any] | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIEvaluationCaseRevision:
        stmt_rec = select(AIEvaluationCaseRecommendation).where(
            AIEvaluationCaseRecommendation.id == uuid.UUID(recommendation_id)
        )
        rec = db.scalar(stmt_rec)
        if not rec:
            raise AppError(
                code="RECOMMENDATION_NOT_FOUND", message="推荐案例不存在", status_code=404
            )

        if rec.status != "PROPOSED":
            raise AppError(
                code="RECOMMENDATION_ALREADY_PROCESSED",
                message="该推荐案例已被处理",
                status_code=400,
            )

        # 1. 创建项目私有 AIEvaluationCase
        case_key = f"case-{uuid.uuid4().hex[:12]}"
        case = AIEvaluationCase(
            id=uuid.uuid4(),
            project_id=rec.project_id,
            scope_type="PROJECT",
            case_key=case_key,
            name=case_name,
        )
        db.add(case)
        db.flush()

        # 2. 计算 Canonical Hash
        case_content = {
            "inputs": redacted_inputs,
            "human_decision_fixture": human_decision_fixture,
            "assertions": declarative_assertions,
            "evaluator_key": "declarative_v1",
        }
        content_hash = compute_canonical_json_hash(case_content)

        # 3. 创建不可变 Case Revision
        case_rev = AIEvaluationCaseRevision(
            id=uuid.uuid4(),
            case_id=case.id,
            revision_no=1,
            revision_hash=content_hash[:32],
            inputs_snapshot_json=redacted_inputs,
            human_decision_fixture_json=human_decision_fixture,
            expected_snapshot_json=None,
            declarative_assertions_json=declarative_assertions,
            source_type="FEEDBACK_RECOMMENDATION"
            if rec.source_type == "FEEDBACK"
            else "ACCEPTED_REVISION_RECOMMENDATION",
            source_ref_id=rec.source_id,
            sensitivity="REDACTED",
            redaction_snapshot_json={
                "redacted_by": actor_id,
                "redacted_at": datetime.now(UTC).isoformat(),
            },
            evaluator_key="declarative_v1",
            evaluator_version="1.0",
            canonical_content_hash=content_hash,
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(case_rev)
        db.flush()

        # 4. 更新 Case current_revision_id & Recommendation 状态
        case.current_revision_id = case_rev.id
        rec.status = "ACCEPTED"
        rec.accepted_case_revision_id = case_rev.id
        rec.reviewed_by = uuid.UUID(actor_id) if actor_id else None
        rec.reviewed_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            action="recommendation.accepted",
            object_type="AIEvaluationCaseRecommendation",
            object_id=str(rec.id),
            summary=f"人工接受并脱敏生成项目评测案例 '{case_name}'",
            project_id=rec.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return case_rev

    # =========================================================================
    # 2. 评测集与不可变 Revision 管理
    # =========================================================================

    @staticmethod
    def create_evaluation_set_revision(
        db: Session,
        set_id: str,
        case_revision_ids: list[str],
        evaluator_profile: dict[str, Any] | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIEvaluationSetRevision:
        stmt_set = select(AIEvaluationSet).where(AIEvaluationSet.id == uuid.UUID(set_id))
        eval_set = db.scalar(stmt_set)
        if not eval_set:
            raise AppError(code="EVALUATION_SET_NOT_FOUND", message="评测集不存在", status_code=404)

        # 获取历史 Revision 最大序号
        stmt_max = (
            select(AIEvaluationSetRevision.revision_no)
            .where(AIEvaluationSetRevision.set_id == eval_set.id)
            .order_by(AIEvaluationSetRevision.revision_no.desc())
        )
        max_no = db.scalar(stmt_max) or 0
        new_rev_no = max_no + 1

        profile = evaluator_profile or {"evaluator": "declarative_v1", "assertions_strict": True}
        rev_hash = compute_canonical_json_hash(
            {
                "set_id": str(eval_set.id),
                "revision_no": new_rev_no,
                "case_revision_ids": sorted(case_revision_ids),
                "evaluator_profile": profile,
            }
        )

        set_rev = AIEvaluationSetRevision(
            id=uuid.uuid4(),
            set_id=eval_set.id,
            revision_no=new_rev_no,
            revision_hash=rev_hash,
            evaluator_profile_json=profile,
            is_frozen=True,
            case_count=len(case_revision_ids),
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(set_rev)
        db.flush()

        # 关联 Case Revisions
        for pos, case_rev_id in enumerate(case_revision_ids):
            item = AIEvaluationSetRevisionCase(
                id=uuid.uuid4(),
                set_revision_id=set_rev.id,
                case_revision_id=uuid.UUID(case_rev_id),
                position=pos,
                weight=1.0,
            )
            db.add(item)

        eval_set.current_revision_id = set_rev.id
        db.flush()

        AuditService.log_event(
            db,
            action="evaluation_set.revision_created",
            object_type="AIEvaluationSetRevision",
            object_id=str(set_rev.id),
            summary=f"成功创建评测集 '{eval_set.name}' 的不可变 Revision r{new_rev_no}",
            project_id=eval_set.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return set_rev

    # =========================================================================
    # 3. 评测运行与结果指标汇总
    # =========================================================================

    @staticmethod
    def create_evaluation_run(
        db: Session,
        capability_id: str,
        capability_version_id: str,
        set_revision_id: str,
        repetitions: int = 1,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIEvaluationRun:
        stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
        cap = db.scalar(stmt_cap)
        if not cap:
            raise AppError(code="CAPABILITY_NOT_FOUND", message="AI 能力不存在", status_code=404)

        stmt_ver = select(AICapabilityVersion).where(
            AICapabilityVersion.id == uuid.UUID(capability_version_id),
            AICapabilityVersion.capability_id == cap.id,
        )
        ver = db.scalar(stmt_ver)
        if not ver:
            raise AppError(
                code="VERSION_NOT_FOUND", message="指定的能力版本不存在", status_code=404
            )

        stmt_srev = select(AIEvaluationSetRevision).where(
            AIEvaluationSetRevision.id == uuid.UUID(set_revision_id)
        )
        set_rev = db.scalar(stmt_srev)
        if not set_rev:
            raise AppError(
                code="SET_REVISION_NOT_FOUND", message="评测集 Revision 不存在", status_code=404
            )

        # 获取该 Set Revision 下包含的所有 Case Revisions
        stmt_cases = (
            select(AIEvaluationSetRevisionCase)
            .where(AIEvaluationSetRevisionCase.set_revision_id == set_rev.id)
            .order_by(AIEvaluationSetRevisionCase.position.asc())
        )
        set_cases = db.scalars(stmt_cases).all()

        total_cases_count = len(set_cases) * repetitions

        eval_run = AIEvaluationRun(
            id=uuid.uuid4(),
            project_id=cap.project_id,
            capability_id=cap.id,
            capability_version_id=ver.id,
            package_fingerprint=ver.package_fingerprint or "unknown",
            set_revision_id=set_rev.id,
            set_revision_hash=set_rev.revision_hash,
            evaluator_profile_hash=compute_canonical_json_hash(set_rev.evaluator_profile_json),
            runtime_profile_hash=compute_canonical_json_hash({"runtime": "M09_P2_RUNTIME"}),
            model_provider="default_provider",
            model_name="default_model",
            model_parameters_json={"temperature": 0.0},
            status="PENDING",
            total_cases=total_cases_count,
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(eval_run)
        db.flush()

        # 为每个 Case × repetition 初始化 Result 占位实体
        for set_c in set_cases:
            for rep in range(repetitions):
                res = AIEvaluationResult(
                    id=uuid.uuid4(),
                    evaluation_run_id=eval_run.id,
                    case_revision_id=set_c.case_revision_id,
                    repetition_index=rep,
                    status="PENDING",
                )
                db.add(res)

        db.flush()
        return eval_run

    # =========================================================================
    # 4. 新旧版本评测结果比对
    # =========================================================================

    @staticmethod
    def create_comparison(
        db: Session,
        baseline_run_id: str,
        candidate_run_id: str,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIEvaluationComparison:
        stmt_b = select(AIEvaluationRun).where(AIEvaluationRun.id == uuid.UUID(baseline_run_id))
        base_run = db.scalar(stmt_b)
        stmt_c = select(AIEvaluationRun).where(AIEvaluationRun.id == uuid.UUID(candidate_run_id))
        cand_run = db.scalar(stmt_c)

        if not base_run or not cand_run:
            raise AppError(
                code="EVALUATION_RUN_NOT_FOUND", message="评测 Run 不存在", status_code=404
            )

        if base_run.capability_id != cand_run.capability_id:
            raise AppError(
                code="CAPABILITY_MISMATCH",
                message="无法比对属于不同能力的评测结果",
                status_code=400,
            )

        # 检查可比较性条件
        not_comparable_reason: str | None = None
        if base_run.set_revision_id != cand_run.set_revision_id:
            not_comparable_reason = "SET_REVISION_MISMATCH"
        elif base_run.evaluator_profile_hash != cand_run.evaluator_profile_hash:
            not_comparable_reason = "EVALUATOR_PROFILE_MISMATCH"
        elif base_run.status != "COMPLETED" or cand_run.status != "COMPLETED":
            not_comparable_reason = "EVALUATION_NOT_COMPLETED"

        comp_status = "NOT_COMPARABLE" if not_comparable_reason else "READY"

        comparison = AIEvaluationComparison(
            id=uuid.uuid4(),
            project_id=cand_run.project_id,
            capability_id=cand_run.capability_id,
            baseline_run_id=base_run.id,
            candidate_run_id=cand_run.id,
            baseline_version_id=base_run.capability_version_id,
            candidate_version_id=cand_run.capability_version_id,
            status=comp_status,
            not_comparable_reason=not_comparable_reason,
            summary_diff_json=None,
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(comparison)
        db.flush()

        if comp_status == "READY":
            # 执行逐案例配对比对
            stmt_b_res = select(AIEvaluationResult).where(
                AIEvaluationResult.evaluation_run_id == base_run.id
            )
            b_results = {
                (r.case_revision_id, r.repetition_index): r for r in db.scalars(stmt_b_res).all()
            }

            stmt_c_res = select(AIEvaluationResult).where(
                AIEvaluationResult.evaluation_run_id == cand_run.id
            )
            c_results = {
                (r.case_revision_id, r.repetition_index): r for r in db.scalars(stmt_c_res).all()
            }

            all_keys = set(b_results.keys()).union(set(c_results.keys()))
            item_diffs: list[dict[str, Any]] = []

            for case_rev_id, rep_idx in all_keys:
                b_r = b_results.get((case_rev_id, rep_idx))
                c_r = c_results.get((case_rev_id, rep_idx))

                b_status = b_r.status if b_r else "MISSING"
                c_status = c_r.status if c_r else "MISSING"

                item = AIEvaluationComparisonItem(
                    id=uuid.uuid4(),
                    comparison_id=comparison.id,
                    case_revision_id=case_rev_id,
                    repetition_index=rep_idx,
                    baseline_result_id=b_r.id if b_r else None,
                    candidate_result_id=c_r.id if c_r else None,
                    baseline_status=b_status,
                    candidate_status=c_status,
                    delta_json={
                        "status_changed": b_status != c_status,
                        "duration_delta_ms": (c_r.duration_ms or 0) - (b_r.duration_ms or 0)
                        if (c_r and b_r)
                        else None,
                    },
                )
                db.add(item)
                item_diffs.append(
                    {"case_revision_id": str(case_rev_id), "status_changed": b_status != c_status}
                )

            comparison.summary_diff_json = {
                "total_compared_cases": len(all_keys),
                "items_diff": item_diffs,
            }

        db.flush()

        AuditService.log_event(
            db,
            action="evaluation.comparison_created",
            object_type="AIEvaluationComparison",
            object_id=str(comparison.id),
            summary=f"完成能力版本评测比对 (状态: {comp_status}, 原因: {not_comparable_reason or 'None'})",
            project_id=cand_run.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return comparison
