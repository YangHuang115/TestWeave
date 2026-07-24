import uuid
from typing import Any

from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import AICapability, AICapabilityPackage, AICapabilityVersion


class DraftSyncService:
    @classmethod
    def sync_capability_draft(
        cls,
        db: Session,
        token_project_id: uuid.UUID,
        user_id: uuid.UUID,
        effective_scopes: list[str],
        capability_id: uuid.UUID,
        version_name: str,
        files_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        # 1. 校验 Token 作用域权限 (需包含 workspace:spec 或 revision:candidate)
        if (
            "workspace:spec" not in effective_scopes
            and "revision:candidate" not in effective_scopes
        ):
            raise AppError(
                code="SCOPE_PERMISSION_DENIED",
                message="缺少必要的草稿同步 Scope 权限 (workspace:spec 或 revision:candidate)",
                status_code=403,
            )

        # 2. 校验 Capability 项目归属
        capability = db.get(AICapability, capability_id)
        if not capability or (
            capability.scope == "PROJECT" and capability.project_id != token_project_id
        ):
            raise AppError(
                code="CAPABILITY_NOT_FOUND",
                message="能力包不存在或不属于当前 Token 项目",
                status_code=404,
            )

        # 3. 创建草稿 Version
        draft_version = AICapabilityVersion(
            capability_id=capability.id,
            version=version_name,
            status="SYNCED_DRAFT",
            package_fingerprint=f"draft_sync_{uuid.uuid4().hex[:12]}",
            created_source="EXTERNAL_SYNC",
            created_by=user_id,
        )
        db.add(draft_version)
        db.flush()

        # 4. 保存文件快照 Package
        pkg = AICapabilityPackage(
            capability_version_id=draft_version.id,
            package_fingerprint=draft_version.package_fingerprint or "draft_fp",
            files_snapshot=files_snapshot,
        )
        db.add(pkg)
        db.commit()

        return {
            "status": "SYNCED",
            "capabilityId": str(capability.id),
            "versionId": str(draft_version.id),
            "versionName": version_name,
            "packageFingerprint": draft_version.package_fingerprint,
        }
