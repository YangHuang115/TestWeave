import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityDeployment,
    AICapabilityReleaseAction,
    AICapabilityReleaseRequest,
    AICapabilityVersion,
    AIEvaluationComparison,
    AIEvaluationRun,
)
from testweave.modules.ai_capabilities.p5_helpers import (
    compute_canary_bucket,
    compute_canonical_json_hash,
)
from testweave.modules.audit.service import AuditService


class ReleasePolicyProvider:
    """窄接口 ReleasePolicyProvider：平台无自定义规则时返回 NO_CONFIGURED_QUALITY_RULES。"""

    @staticmethod
    def evaluate_release_policy(
        db: Session,
        capability: AICapability,
        candidate_version: AICapabilityVersion,
        base_version: AICapabilityVersion | None,
        evaluation_run: AIEvaluationRun | None,
        comparison: AIEvaluationComparison | None,
    ) -> dict[str, Any]:
        blocking_checks: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []

        # 1. 基础硬性不变量校验 (Blockers)
        if candidate_version.capability_id != capability.id:
            blocking_checks.append(
                {
                    "code": "VERSION_CAPABILITY_MISMATCH",
                    "message": "候选版本不属于该 AI 能力",
                }
            )

        # 校验版本包含的包指纹/完整性
        if not candidate_version.package_fingerprint:
            blocking_checks.append(
                {
                    "code": "MISSING_PACKAGE_FINGERPRINT",
                    "message": "候选版本缺少不可变包指纹",
                }
            )

        # 2. 软性评估提示 (Advisories)
        if base_version and comparison:
            if comparison.status == "NOT_COMPARABLE":
                advisories.append(
                    {
                        "code": "COMPARISON_NOT_COMPARABLE",
                        "message": f"评测比对结果为不可比 ({comparison.not_comparable_reason or '数据集版本或结构不匹配'})",
                    }
                )
            elif comparison.summary_diff_json:
                metrics_diff = comparison.summary_diff_json.get("metrics_diff", {})
                for m_key, diff in metrics_diff.items():
                    if diff.get("is_regression"):
                        advisories.append(
                            {
                                "code": "METRIC_REGRESSION",
                                "message": f"指标 '{m_key}' 存在下降: 基准 {diff.get('baseline')} -> 候选 {diff.get('candidate')}",
                                "metric_key": m_key,
                            }
                        )

        if not evaluation_run or evaluation_run.status != "COMPLETED":
            advisories.append(
                {
                    "code": "EVALUATION_NOT_COMPLETED",
                    "message": "候选版本尚未完成完整测试集评测或评测未达到 COMPLETED 状态",
                }
            )

        return {
            "policy_status": "NO_CONFIGURED_QUALITY_RULES",
            "evaluated_at": datetime.now(UTC).isoformat(),
            "blocking_checks": blocking_checks,
            "advisories": advisories,
            "policy_hash": compute_canonical_json_hash({"policy": "NO_CONFIGURED_QUALITY_RULES"}),
        }


class ReleaseResolver:
    """灰度分流解析器：将新 NORMAL Run 路由分配至 Stable 或 Canary 版本。"""

    @staticmethod
    def resolve_run_deployment(
        db: Session,
        capability_id: str,
        routing_subject: str,
        explicit_version_id: str | None = None,
        run_mode: str = "NORMAL",
    ) -> tuple[AICapabilityDeployment, AICapabilityVersion, dict[str, Any]]:
        # 1. 显式选择版本 (仅 PREVIEW / EVALUATION 模式允许)
        if explicit_version_id and run_mode in ("PREVIEW", "EVALUATION"):
            stmt_v = select(AICapabilityVersion).where(
                AICapabilityVersion.id == uuid.UUID(explicit_version_id),
                AICapabilityVersion.capability_id == uuid.UUID(capability_id),
            )
            v = db.scalar(stmt_v)
            if not v:
                raise AppError(
                    code="VERSION_NOT_FOUND", message="指定的 AI 能力版本不存在", status_code=404
                )

            # 获取或初始化默认 Deployment
            stmt_d = select(AICapabilityDeployment).where(
                AICapabilityDeployment.capability_id == uuid.UUID(capability_id)
            )
            deploy = db.scalar(stmt_d)
            if not deploy:
                deploy = ReleaseService.ensure_deployment_exists(db, capability_id, v.id)

            routing_info = {
                "deployment_id": str(deploy.id),
                "deployment_revision": deploy.deployment_revision,
                "selected_version_id": str(v.id),
                "is_canary": False,
                "bucket": 0,
                "routing_reason": f"EXPLICIT_SELECTION_{run_mode}",
            }
            return deploy, v, routing_info

        # 2. 普通 NORMAL Run 必须经过 Deployment Canary 路由
        stmt_d = select(AICapabilityDeployment).where(
            AICapabilityDeployment.capability_id == uuid.UUID(capability_id)
        )
        deploy = db.scalar(stmt_d)
        if not deploy:
            stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
            cap = db.scalar(stmt_cap)
            if not cap or not cap.current_published_version_id:
                raise AppError(
                    code="CAPABILITY_NOT_RELEASED",
                    message="该能力尚未进行首次发布，无法发起 NORMAL 运行",
                    status_code=400,
                )
            deploy = ReleaseService.ensure_deployment_exists(
                db, capability_id, cap.current_published_version_id
            )

        # 3. 计算 Canary 分桶
        bucket = compute_canary_bucket(
            deployment_id=str(deploy.id),
            project_id=str(deploy.project_id) if deploy.project_id else None,
            capability_id=str(deploy.capability_id),
            routing_subject=routing_subject,
            routing_salt=deploy.routing_salt,
        )

        selected_version_id = deploy.stable_version_id
        is_canary = False
        reason = "STABLE_DEFAULT"

        if deploy.canary_version_id and deploy.canary_basis_points > 0:
            if bucket < deploy.canary_basis_points:
                selected_version_id = deploy.canary_version_id
                is_canary = True
                reason = f"CANARY_MATCHED_{bucket}_LT_{deploy.canary_basis_points}"
            else:
                reason = f"STABLE_FALLBACK_{bucket}_GE_{deploy.canary_basis_points}"

        stmt_version = select(AICapabilityVersion).where(
            AICapabilityVersion.id == selected_version_id
        )
        version = db.scalar(stmt_version)
        if not version:
            raise AppError(
                code="DEPLOYED_VERSION_NOT_FOUND", message="当前部署的版本不存在", status_code=500
            )

        routing_info = {
            "deployment_id": str(deploy.id),
            "deployment_revision": deploy.deployment_revision,
            "selected_version_id": str(version.id),
            "is_canary": is_canary,
            "bucket": bucket,
            "routing_reason": reason,
        }
        return deploy, version, routing_info


class ReleaseService:
    """AI 能力发布、灰度控制与回滚核心服务。"""

    @staticmethod
    def ensure_deployment_exists(
        db: Session, capability_id: str, default_version_id: uuid.UUID
    ) -> AICapabilityDeployment:
        stmt = select(AICapabilityDeployment).where(
            AICapabilityDeployment.capability_id == uuid.UUID(capability_id)
        )
        deploy = db.scalar(stmt)
        if deploy:
            return deploy

        stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
        cap = db.scalar(stmt_cap)
        if not cap:
            raise AppError(code="CAPABILITY_NOT_FOUND", message="AI 能力不存在", status_code=404)

        salt = compute_canonical_json_hash(
            {"salt_seed": str(uuid.uuid4()), "time": datetime.now(UTC).isoformat()}
        )
        deploy = AICapabilityDeployment(
            id=uuid.uuid4(),
            project_id=cap.project_id,
            capability_id=cap.id,
            stable_version_id=default_version_id,
            canary_version_id=None,
            canary_basis_points=0,
            routing_salt=salt[:32],
            deployment_revision=1,
            row_version=1,
            status="ACTIVE",
        )
        db.add(deploy)

        # 记录初始全量发布不可变历史
        action = AICapabilityReleaseAction(
            id=uuid.uuid4(),
            project_id=cap.project_id,
            capability_id=cap.id,
            deployment_id=deploy.id,
            release_request_id=None,
            action_type="FULL_RELEASE",
            stable_version_id=default_version_id,
            canary_version_id=None,
            canary_basis_points=0,
            deployment_revision=1,
            reason="Initial deployment initialization",
            actor_id=None,
        )
        db.add(action)

        db.flush()
        return deploy

    @staticmethod
    def create_release_request(
        db: Session,
        project_id: str | None,
        capability_id: str,
        candidate_version_id: str,
        evaluation_run_id: str | None = None,
        comparison_id: str | None = None,
        reason: str | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AICapabilityReleaseRequest:
        stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
        cap = db.scalar(stmt_cap)
        if not cap:
            raise AppError(code="CAPABILITY_NOT_FOUND", message="AI 能力不存在", status_code=404)

        if project_id and cap.project_id and str(cap.project_id) != project_id:
            raise AppError(
                code="PROJECT_MISMATCH", message="跨项目能力无法进行发布请求", status_code=403
            )

        stmt_cand = select(AICapabilityVersion).where(
            AICapabilityVersion.id == uuid.UUID(candidate_version_id),
            AICapabilityVersion.capability_id == cap.id,
        )
        cand_v = db.scalar(stmt_cand)
        if not cand_v:
            raise AppError(
                code="VERSION_NOT_FOUND", message="候选版本不存在或不属于该能力", status_code=404
            )

        # 获取 Base Version
        base_v: AICapabilityVersion | None = None
        if cap.current_published_version_id:
            stmt_base = select(AICapabilityVersion).where(
                AICapabilityVersion.id == cap.current_published_version_id
            )
            base_v = db.scalar(stmt_base)

        eval_run: AIEvaluationRun | None = None
        if evaluation_run_id:
            stmt_eval = select(AIEvaluationRun).where(
                AIEvaluationRun.id == uuid.UUID(evaluation_run_id)
            )
            eval_run = db.scalar(stmt_eval)

        comp: AIEvaluationComparison | None = None
        if comparison_id:
            stmt_comp = select(AIEvaluationComparison).where(
                AIEvaluationComparison.id == uuid.UUID(comparison_id)
            )
            comp = db.scalar(stmt_comp)

        # 评估 Release Policy
        policy_res = ReleasePolicyProvider.evaluate_release_policy(
            db=db,
            capability=cap,
            candidate_version=cand_v,
            base_version=base_v,
            evaluation_run=eval_run,
            comparison=comp,
        )

        req_fingerprint = compute_canonical_json_hash(
            {
                "capability_id": str(cap.id),
                "candidate_version_id": str(cand_v.id),
                "base_version_id": str(base_v.id) if base_v else None,
                "policy": policy_res,
            }
        )

        rel_req = AICapabilityReleaseRequest(
            id=uuid.uuid4(),
            project_id=cap.project_id,
            capability_id=cap.id,
            candidate_version_id=cand_v.id,
            base_version_id=base_v.id if base_v else None,
            package_fingerprints_json=[cand_v.package_fingerprint]
            if cand_v.package_fingerprint
            else [],
            evaluation_run_id=eval_run.id if eval_run else None,
            comparison_id=comp.id if comp else None,
            config_diff_json={"version": cand_v.version},
            blocking_checks_json=policy_res["blocking_checks"],
            advisories_json=policy_res["advisories"],
            policy_provider_snapshot_json=policy_res,
            rollback_target_version_id=base_v.id if base_v else None,
            status="APPROVED" if not policy_res["blocking_checks"] else "REJECTED",
            request_fingerprint=req_fingerprint,
            reason=reason,
            requested_by=uuid.UUID(actor_id) if actor_id else None,
            reviewed_by=uuid.UUID(actor_id) if actor_id else None,
            reviewed_at=datetime.now(UTC),
        )
        db.add(rel_req)
        db.flush()

        AuditService.log_event(
            db,
            action="release_request.created",
            object_type="AICapabilityReleaseRequest",
            object_id=str(rel_req.id),
            summary=f"创建发布评审请求 (候选版本: {cand_v.version}, 状态: {rel_req.status})",
            project_id=cap.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return rel_req

    @staticmethod
    def start_canary(
        db: Session,
        release_request_id: str,
        canary_basis_points: int,
        reason: str,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AICapabilityDeployment:
        if not (1 <= canary_basis_points <= 9999):
            raise AppError(
                code="INVALID_CANARY_BASIS_POINTS",
                message="灰度比例必须在 1 到 9999 之间 (0.01% - 99.99%)",
                status_code=400,
            )

        stmt_req = select(AICapabilityReleaseRequest).where(
            AICapabilityReleaseRequest.id == uuid.UUID(release_request_id)
        )
        rel_req = db.scalar(stmt_req)
        if not rel_req:
            raise AppError(
                code="RELEASE_REQUEST_NOT_FOUND", message="发布请求不存在", status_code=404
            )

        if rel_req.blocking_checks_json:
            raise AppError(
                code="RELEASE_BLOCKED", message="发布请求包含阻断项，无法开启灰度", status_code=400
            )

        deploy = ReleaseService.ensure_deployment_exists(
            db, str(rel_req.capability_id), rel_req.candidate_version_id
        )
        if not deploy.stable_version_id:
            raise AppError(
                code="FIRST_RELEASE_CANNOT_CANARY",
                message="首次发布没有 Stable 版本，不能直接灰度发布，必须全量发布",
                status_code=400,
            )

        # 校验并生成 Canary
        salt = compute_canonical_json_hash(
            {"salt_seed": str(uuid.uuid4()), "time": datetime.now(UTC).isoformat()}
        )
        deploy.canary_version_id = rel_req.candidate_version_id
        deploy.canary_basis_points = canary_basis_points
        deploy.routing_salt = salt[:32]
        deploy.deployment_revision += 1
        deploy.row_version += 1
        deploy.active_release_request_id = rel_req.id
        rel_req.status = "RELEASED"

        # 记录操作历史
        action = AICapabilityReleaseAction(
            id=uuid.uuid4(),
            project_id=deploy.project_id,
            capability_id=deploy.capability_id,
            deployment_id=deploy.id,
            release_request_id=rel_req.id,
            action_type="START_CANARY",
            stable_version_id=deploy.stable_version_id,
            canary_version_id=deploy.canary_version_id,
            canary_basis_points=canary_basis_points,
            deployment_revision=deploy.deployment_revision,
            reason=reason,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(action)
        db.flush()

        AuditService.log_event(
            db,
            action="release.start_canary",
            object_type="AICapabilityDeployment",
            object_id=str(deploy.id),
            summary=f"能力开启灰度发布 ({canary_basis_points / 100}%)",
            project_id=deploy.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return deploy

    @staticmethod
    def adjust_canary(
        db: Session,
        deployment_id: str,
        canary_basis_points: int,
        reason: str,
        expected_deployment_revision: int,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AICapabilityDeployment:
        if not (1 <= canary_basis_points <= 9999):
            raise AppError(
                code="INVALID_CANARY_BASIS_POINTS",
                message="灰度比例必须在 1 到 9999 之间",
                status_code=400,
            )

        stmt = select(AICapabilityDeployment).where(
            AICapabilityDeployment.id == uuid.UUID(deployment_id)
        )
        deploy = db.scalar(stmt)
        if not deploy:
            raise AppError(code="DEPLOYMENT_NOT_FOUND", message="部署记录不存在", status_code=404)

        if deploy.deployment_revision != expected_deployment_revision:
            raise AppError(
                code="CAS_REVISION_MISMATCH",
                message="部署版本已发生变更，请刷新后重试",
                status_code=409,
            )

        if not deploy.canary_version_id:
            raise AppError(code="NO_ACTIVE_CANARY", message="当前没有活动灰度分支", status_code=400)

        # 调整比例保持 routing_salt 不变
        deploy.canary_basis_points = canary_basis_points
        deploy.deployment_revision += 1
        deploy.row_version += 1

        action = AICapabilityReleaseAction(
            id=uuid.uuid4(),
            project_id=deploy.project_id,
            capability_id=deploy.capability_id,
            deployment_id=deploy.id,
            release_request_id=deploy.active_release_request_id,
            action_type="ADJUST_CANARY",
            stable_version_id=deploy.stable_version_id,
            canary_version_id=deploy.canary_version_id,
            canary_basis_points=canary_basis_points,
            deployment_revision=deploy.deployment_revision,
            reason=reason,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(action)
        db.flush()

        AuditService.log_event(
            db,
            action="release.adjust_canary",
            object_type="AICapabilityDeployment",
            object_id=str(deploy.id),
            summary=f"调整灰度比例至 {canary_basis_points / 100}%",
            project_id=deploy.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return deploy

    @staticmethod
    def promote(
        db: Session,
        deployment_id: str,
        reason: str,
        expected_deployment_revision: int,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AICapabilityDeployment:
        stmt = select(AICapabilityDeployment).where(
            AICapabilityDeployment.id == uuid.UUID(deployment_id)
        )
        deploy = db.scalar(stmt)
        if not deploy:
            raise AppError(code="DEPLOYMENT_NOT_FOUND", message="部署记录不存在", status_code=404)

        if deploy.deployment_revision != expected_deployment_revision:
            raise AppError(
                code="CAS_REVISION_MISMATCH",
                message="部署版本已发生变更，请刷新后重试",
                status_code=409,
            )

        target_version_id = deploy.canary_version_id or deploy.stable_version_id

        # 原子全量晋级
        deploy.stable_version_id = target_version_id
        deploy.canary_version_id = None
        deploy.canary_basis_points = 0
        deploy.deployment_revision += 1
        deploy.row_version += 1

        # 更新 Capability 主表的 current_published_version_id
        stmt_cap = select(AICapability).where(AICapability.id == deploy.capability_id)
        cap = db.scalar(stmt_cap)
        if cap:
            cap.current_published_version_id = target_version_id
            cap.status = "ACTIVE"

        # 将 Version 状态由 SYNCED_DRAFT 转为 VALIDATING/PUBLISHED
        stmt_v = select(AICapabilityVersion).where(AICapabilityVersion.id == target_version_id)
        ver = db.scalar(stmt_v)
        if ver and ver.status == "SYNCED_DRAFT":
            ver.status = "PUBLISHED"

        action = AICapabilityReleaseAction(
            id=uuid.uuid4(),
            project_id=deploy.project_id,
            capability_id=deploy.capability_id,
            deployment_id=deploy.id,
            release_request_id=deploy.active_release_request_id,
            action_type="FULL_RELEASE" if not deploy.canary_version_id else "PROMOTE_CANARY",
            stable_version_id=deploy.stable_version_id,
            canary_version_id=None,
            canary_basis_points=0,
            deployment_revision=deploy.deployment_revision,
            reason=reason,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(action)
        db.flush()

        AuditService.log_event(
            db,
            action="release.promote",
            object_type="AICapabilityDeployment",
            object_id=str(deploy.id),
            summary=f"全量晋级部署版本为 {target_version_id}",
            project_id=deploy.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return deploy

    @staticmethod
    def rollback(
        db: Session,
        capability_id: str,
        target_version_id: str,
        reason: str,
        expected_deployment_revision: int,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AICapabilityDeployment:
        if not reason or not reason.strip():
            raise AppError(
                code="ROLLBACK_REASON_REQUIRED", message="回滚必须填写明确的原因", status_code=400
            )

        stmt_d = select(AICapabilityDeployment).where(
            AICapabilityDeployment.capability_id == uuid.UUID(capability_id)
        )
        deploy = db.scalar(stmt_d)
        if not deploy:
            raise AppError(code="DEPLOYMENT_NOT_FOUND", message="部署记录不存在", status_code=404)

        if deploy.deployment_revision != expected_deployment_revision:
            raise AppError(
                code="CAS_REVISION_MISMATCH",
                message="部署版本已发生变更，请刷新后重试",
                status_code=409,
            )

        target_uuid = uuid.UUID(target_version_id)

        # 校验目标版本是否在不可变历史中曾成功全量发布过
        stmt_hist = select(AICapabilityReleaseAction).where(
            AICapabilityReleaseAction.capability_id == deploy.capability_id,
            AICapabilityReleaseAction.stable_version_id == target_uuid,
            AICapabilityReleaseAction.action_type.in_(
                ["FULL_RELEASE", "PROMOTE_CANARY", "ROLLBACK"]
            ),
        )
        has_history = db.scalar(stmt_hist)
        if not has_history and str(deploy.stable_version_id) != target_version_id:
            raise AppError(
                code="INELIGIBLE_ROLLBACK_TARGET",
                message="回滚目标必须在不可变发布历史中曾成功全量发布过",
                status_code=400,
            )

        # 执行回滚
        deploy.stable_version_id = target_uuid
        deploy.canary_version_id = None
        deploy.canary_basis_points = 0
        deploy.deployment_revision += 1
        deploy.row_version += 1

        stmt_cap = select(AICapability).where(AICapability.id == deploy.capability_id)
        cap = db.scalar(stmt_cap)
        if cap:
            cap.current_published_version_id = target_uuid

        action = AICapabilityReleaseAction(
            id=uuid.uuid4(),
            project_id=deploy.project_id,
            capability_id=deploy.capability_id,
            deployment_id=deploy.id,
            release_request_id=None,
            action_type="ROLLBACK",
            stable_version_id=deploy.stable_version_id,
            canary_version_id=None,
            canary_basis_points=0,
            deployment_revision=deploy.deployment_revision,
            reason=reason.strip(),
            actor_id=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(action)
        db.flush()

        AuditService.log_event(
            db,
            action="release.rollback",
            object_type="AICapabilityDeployment",
            object_id=str(deploy.id),
            summary=f"能力成功回滚至历史版本 {target_version_id} (原因: {reason})",
            project_id=deploy.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return deploy
