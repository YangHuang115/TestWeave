import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import AICapability, AICapabilityPackage, AICapabilityVersion
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)

SUPPORTED_CANDIDATE_SCHEMAS = ["test_point_set@1.0", "test_case_set@1.0"]


class WorkspaceSpecService:
    @staticmethod
    def generate_workspace_spec(
        db: Session,
        target_id: uuid.UUID | None,
        effective_scopes: list[str],
        project_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        ExternalAgentTokenService.verify_scope(effective_scopes, "workspace:spec")

        capability = None
        version = None

        if target_id:
            # 支持 target_id 为 capability_id 或 version_id
            version = db.get(AICapabilityVersion, target_id)
            if version:
                capability = db.get(AICapability, version.capability_id)
            else:
                capability = db.get(AICapability, target_id)

        # 如果未指定 target_id 或未找到，且传入了 project_id，自动查找该项目下的能力包
        if not capability and project_id:
            stmt = (
                select(AICapability)
                .where(AICapability.project_id == project_id)
                .order_by(AICapability.created_at.desc())
            )
            capability = db.scalar(stmt)

        # 如果项目尚无能力包，自动为项目自动准备内置默认能力包
        if not capability and project_id:
            capability = AICapability(
                project_id=project_id,
                scope="PROJECT",
                namespace="testweave",
                code="default_test_point_generation",
                name="默认 AI 测试点与用例生成能力包",
                category="TEST_POINT_GENERATION",
            )
            db.add(capability)
            db.flush()

        if capability and not version:
            if capability.current_published_version_id:
                version = db.get(AICapabilityVersion, capability.current_published_version_id)
            else:
                stmt = (
                    select(AICapabilityVersion)
                    .where(AICapabilityVersion.capability_id == capability.id)
                    .order_by(AICapabilityVersion.created_at.desc())
                )
                version = db.scalar(stmt)

        # 如果该能力包尚未创建版本，自动准备默认初始版本 1.0.0
        if capability and not version:
            version = AICapabilityVersion(
                capability_id=capability.id,
                version="1.0.0",
                status="PUBLISHED",
                package_fingerprint=f"default_fp_{uuid.uuid4().hex[:8]}",
                created_source="SYSTEM_INITIAL",
                created_by=user_id,
            )
            db.add(version)
            db.flush()
            capability.current_published_version_id = version.id
            db.commit()

        if not capability or not version:
            raise AppError(
                code="CAPABILITY_VERSION_NOT_FOUND",
                message="找不到对应能力包或版本定义",
                status_code=404,
            )

        pkg_stmt = select(AICapabilityPackage).where(
            AICapabilityPackage.capability_version_id == version.id
        )
        pkg = db.scalar(pkg_stmt)

        template_files: list[dict[str, str]] = []
        if pkg and isinstance(pkg.files_snapshot, dict) and "files" in pkg.files_snapshot:
            for f in pkg.files_snapshot["files"]:
                template_files.append(
                    {
                        "path": f["path"],
                        "content": f.content if hasattr(f, "content") else f.get("content", ""),
                    }
                )
        else:
            # 提供通用外接 Node Agent 客户端 Starter 骨架
            template_files = [
                {
                    "path": "README.md",
                    "content": f"# External Agent for {capability.name}\n\nProtocol Version: 1.0\n",
                },
                {
                    "path": "schemas/output.json",
                    "content": str(version.output_schema or {}),
                },
            ]

        return {
            "specVersion": "1.0",
            "capability": {
                "id": str(capability.id),
                "key": capability.code,
                "name": capability.name,
                "versionId": str(version.id),
                "version": version.version,
                "packageFingerprint": version.package_fingerprint,
                "compatibilityLevel": version.compatibility_level,
            },
            "contract": {
                "inputSchema": version.input_schema,
                "outputSchema": version.output_schema,
                "supportedArtifactTypes": SUPPORTED_CANDIDATE_SCHEMAS,
            },
            "context": {
                "instructions": "请本地执行并把计算产生的候选 Revision/Artifact 流式发布给 TestWeave 无状态 Gateway。",
                "sandboxRequirement": "Loopback only (127.0.0.1)",
            },
            "templates": {
                "files": template_files,
            },
        }
