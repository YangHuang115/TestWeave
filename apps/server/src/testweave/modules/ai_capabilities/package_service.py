import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AIEvaluationResult,
    AIFeedback,
    AIOptimizationSuggestion,
    AIWorkspacePackage,
)
from testweave.modules.ai_capabilities.p5_helpers import compute_canonical_json_hash
from testweave.modules.audit.service import AuditService


class PackageService:
    """优化建议聚合与 Workspace Package 凭证包生成服务。"""

    @staticmethod
    def generate_suggestions_from_evidence(
        db: Session,
        capability_id: str,
        project_id: str | None = None,
        actor_id: str | None = None,
    ) -> list[AIOptimizationSuggestion]:
        stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
        cap = db.scalar(stmt_cap)
        if not cap:
            raise AppError(code="CAPABILITY_NOT_FOUND", message="AI 能力不存在", status_code=404)

        created_suggestions: list[AIOptimizationSuggestion] = []

        # 1. 扫描该 Capability 相关的 Negative Feedback (DISLIKE / EDIT_REGENERATED)
        stmt_fb = select(AIFeedback).where(
            AIFeedback.project_id == cap.project_id,
            AIFeedback.category.in_(["DISLIKE", "EDIT_REGENERATED"]),
        )
        feedbacks = db.scalars(stmt_fb).all()

        if feedbacks:
            evidence_items = [
                {
                    "evidence_id": str(fb.id),
                    "category": fb.category,
                    "comment": fb.comment[:200] if fb.comment else None,
                    "created_at": fb.created_at.isoformat(),
                }
                for fb in feedbacks[:20]
            ]
            suggestion = AIOptimizationSuggestion(
                id=uuid.uuid4(),
                project_id=cap.project_id,
                capability_id=cap.id,
                suggestion_type="PROMPT",
                title=f"提示词与生成结果问题 (基于 {len(evidence_items)} 条用户反馈)",
                description="用户在生产体验或审核中多次提交负面反馈，建议优化提示词 Prompt 结构与示例。",
                evidence_manifest_json={"evidence_type": "FEEDBACK", "items": evidence_items},
                evidence_count=len(evidence_items),
                suggested_action_area="prompt_template",
                risk_assessment="修改 Prompt 可能改变输出格式风格，建议在评测集中验证。",
                uncertainty_note=None,
                status="OPEN",
            )
            db.add(suggestion)
            created_suggestions.append(suggestion)

        # 2. 扫描评测失败集中的 Validator / Schema 错误
        stmt_err = select(AIEvaluationResult).where(
            AIEvaluationResult.status.in_(["FAILED", "ERROR"]),
            AIEvaluationResult.error_code.isnot(None),
        )
        failed_results = db.scalars(stmt_err).all()

        if failed_results:
            err_items = [
                {
                    "evidence_id": str(res.id),
                    "error_code": res.error_code,
                    "error_message": (res.error_message or "")[:200],
                    "case_revision_id": str(res.case_revision_id),
                }
                for res in failed_results[:20]
            ]
            suggestion = AIOptimizationSuggestion(
                id=uuid.uuid4(),
                project_id=cap.project_id,
                capability_id=cap.id,
                suggestion_type="VALIDATOR",
                title=f"校验器与断言断裂 (基于 {len(err_items)} 个失败评测案例)",
                description="评测运行中出现固定的格式校验或计算断言失败，建议修正数据 Schema 或输出 Validator。",
                evidence_manifest_json={"evidence_type": "EVALUATION_FAILURE", "items": err_items},
                evidence_count=len(err_items),
                suggested_action_area="output_schema_and_validator",
                risk_assessment="若收紧 Validator，可能增加极少数复杂输入的打回率。",
                uncertainty_note=None,
                status="OPEN",
            )
            db.add(suggestion)
            created_suggestions.append(suggestion)

        db.flush()
        return created_suggestions

    @staticmethod
    def create_workspace_package(
        db: Session,
        capability_id: str,
        package_type: str,
        base_version_id: str | None = None,
        candidate_version_id: str | None = None,
        suggestion_ids: list[str] | None = None,
        evaluation_set_revision_id: str | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIWorkspacePackage:
        if package_type not in ("FEEDBACK", "EVALUATION", "OPTIMIZATION"):
            raise AppError(
                code="INVALID_PACKAGE_TYPE", message="无效的 Package 类型", status_code=400
            )

        stmt_cap = select(AICapability).where(AICapability.id == uuid.UUID(capability_id))
        cap = db.scalar(stmt_cap)
        if not cap:
            raise AppError(code="CAPABILITY_NOT_FOUND", message="AI 能力不存在", status_code=404)

        selected_suggestions: list[AIOptimizationSuggestion] = []
        if suggestion_ids:
            stmt_sug = select(AIOptimizationSuggestion).where(
                AIOptimizationSuggestion.id.in_([uuid.UUID(s) for s in suggestion_ids]),
                AIOptimizationSuggestion.capability_id == cap.id,
            )
            selected_suggestions = db.scalars(stmt_sug).all()

        # 构建脱敏后的最小证据包
        evidence_manifest = {
            "capability_id": str(cap.id),
            "capability_code": cap.code,
            "package_type": package_type,
            "suggestions": [
                {
                    "id": str(s.id),
                    "type": s.suggestion_type,
                    "title": s.title,
                    "suggested_action_area": s.suggested_action_area,
                    "evidence_manifest": s.evidence_manifest_json,
                }
                for s in selected_suggestions
            ],
            "exported_at": datetime.now(UTC).isoformat(),
        }

        # 计算不可变 Canonical Hash
        pkg_hash = compute_canonical_json_hash(evidence_manifest)

        # 如果同一 Capability 且同 Hash 已存在，直接返回已有记录（幂等）
        stmt_exist = select(AIWorkspacePackage).where(
            AIWorkspacePackage.capability_id == cap.id,
            AIWorkspacePackage.package_hash == pkg_hash,
            AIWorkspacePackage.status == "READY",
        )
        existing_pkg = db.scalar(stmt_exist)
        if existing_pkg:
            return existing_pkg

        pkg = AIWorkspacePackage(
            id=uuid.uuid4(),
            project_id=cap.project_id,
            capability_id=cap.id,
            package_type=package_type,
            package_hash=pkg_hash,
            schema_version="1.0",
            base_version_id=uuid.UUID(base_version_id) if base_version_id else None,
            candidate_version_id=uuid.UUID(candidate_version_id) if candidate_version_id else None,
            evaluation_set_revision_id=uuid.UUID(evaluation_set_revision_id)
            if evaluation_set_revision_id
            else None,
            suggestion_ids_json=suggestion_ids or [],
            evidence_manifest_json=evidence_manifest,
            status="READY",
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(pkg)

        # 状态关联更新：将勾选的 Suggestions 状态设为 PACKAGED
        for sug in selected_suggestions:
            if sug.status == "OPEN":
                sug.status = "PACKAGED"

        db.flush()

        AuditService.log_event(
            db,
            action="workspace_package.created",
            object_type="AIWorkspacePackage",
            object_id=str(pkg.id),
            summary=f"成功导出不可变 Workspace Package (Hash: {pkg_hash[:16]}...)",
            project_id=cap.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return pkg

    @staticmethod
    def revoke_workspace_package(
        db: Session,
        package_id: str,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> AIWorkspacePackage:
        stmt = select(AIWorkspacePackage).where(AIWorkspacePackage.id == uuid.UUID(package_id))
        pkg = db.scalar(stmt)
        if not pkg:
            raise AppError(
                code="PACKAGE_NOT_FOUND", message="Workspace Package 不存在", status_code=404
            )

        pkg.status = "REVOKED"
        pkg.updated_at = datetime.now(UTC)
        db.flush()

        AuditService.log_event(
            db,
            action="workspace_package.revoked",
            object_type="AIWorkspacePackage",
            object_id=str(pkg.id),
            summary=f"成功撤销 Workspace Package (Hash: {pkg.package_hash[:16]}...)",
            project_id=pkg.project_id,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            request_id=request_id or str(uuid.uuid4()),
        )
        return pkg
