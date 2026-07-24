import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import AICapability, AICapabilityPackage, AICapabilityVersion, User
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.shared.permissions import AGENT_MANAGE, PROJECT_READ

router = APIRouter()


# --- 能力包只读 API ---


@router.get(
    "/projects/{projectId}/ai-capabilities",
    summary="获取当前项目可见的能力包列表",
)
def list_ai_capabilities(
    projectId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> Any:
    # 隔离逻辑：只能查官方或当前项目关联的
    stmt = (
        select(AICapability)
        .where(
            or_(
                AICapability.scope == "OFFICIAL",
                and_(AICapability.scope == "PROJECT", AICapability.project_id == projectId),
            )
        )
        .order_by(AICapability.created_at.desc())
    )
    capabilities = db.scalars(stmt).all()

    # 组装返回，不含明文和哈希等敏感字眼
    result = []
    for cap in capabilities:
        result.append(
            {
                "id": str(cap.id),
                "namespace": cap.namespace,
                "code": cap.code,
                "name": cap.name,
                "category": cap.category,
                "scope": cap.scope,
                "status": cap.status,
                "created_at": cap.created_at,
                "updated_at": cap.updated_at,
            }
        )
    return result


@router.get(
    "/projects/{projectId}/ai-capabilities/{capabilityId}",
    summary="获取能力包详情",
)
def get_ai_capability(
    projectId: uuid.UUID,
    capabilityId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> Any:
    cap = db.get(AICapability, capabilityId)
    if not cap:
        raise AppError(code="CAPABILITY_NOT_FOUND", message="能力包不存在", status_code=404)

    # 跨项目安全校验
    if cap.scope == "PROJECT" and cap.project_id != projectId:
        raise AppError(
            code="CAPABILITY_ACCESS_DENIED",
            message="无权访问其他项目的能力包",
            status_code=403,
        )

    return {
        "id": str(cap.id),
        "namespace": cap.namespace,
        "code": cap.code,
        "name": cap.name,
        "category": cap.category,
        "scope": cap.scope,
        "status": cap.status,
        "created_at": cap.created_at,
        "updated_at": cap.updated_at,
    }


@router.get(
    "/projects/{projectId}/ai-capabilities/{capabilityId}/versions",
    summary="获取能力包版本列表",
)
def list_ai_capability_versions(
    projectId: uuid.UUID,
    capabilityId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> Any:
    cap = db.get(AICapability, capabilityId)
    if not cap:
        raise AppError(code="CAPABILITY_NOT_FOUND", message="能力包不存在", status_code=404)

    if cap.scope == "PROJECT" and cap.project_id != projectId:
        raise AppError(
            code="CAPABILITY_ACCESS_DENIED",
            message="无权访问其他项目的能力包",
            status_code=403,
        )

    stmt = (
        select(AICapabilityVersion)
        .where(AICapabilityVersion.capability_id == capabilityId)
        .order_by(AICapabilityVersion.created_at.desc())
    )
    versions = db.scalars(stmt).all()

    result = []
    for ver in versions:
        result.append(
            {
                "id": str(ver.id),
                "capability_id": str(ver.capability_id),
                "version": ver.version,
                "status": ver.status,
                "package_fingerprint": ver.package_fingerprint,
                "compatibility_level": ver.compatibility_level,
                "created_source": ver.created_source,
                "created_at": ver.created_at,
            }
        )
    return result


@router.get(
    "/projects/{projectId}/ai-capabilities/{capabilityId}/versions/{versionId}",
    summary="获取能力包版本详情",
)
def get_ai_capability_version(
    projectId: uuid.UUID,
    capabilityId: uuid.UUID,
    versionId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> Any:
    cap = db.get(AICapability, capabilityId)
    if not cap:
        raise AppError(code="CAPABILITY_NOT_FOUND", message="能力包不存在", status_code=404)

    if cap.scope == "PROJECT" and cap.project_id != projectId:
        raise AppError(
            code="CAPABILITY_ACCESS_DENIED",
            message="无权访问其他项目的能力包",
            status_code=403,
        )

    ver = db.get(AICapabilityVersion, versionId)
    if not ver or ver.capability_id != capabilityId:
        raise AppError(code="VERSION_NOT_FOUND", message="能力包版本不存在", status_code=404)

    stmt_pkg = select(AICapabilityPackage).where(
        AICapabilityPackage.capability_version_id == versionId
    )
    pkg = db.scalar(stmt_pkg)

    # 提取文件路径清单（不暴露物理临时存储路径）
    files_list = []
    if pkg and "files" in pkg.files_snapshot:
        for f in pkg.files_snapshot["files"]:
            files_list.append({"path": f["path"], "size": len(f["content"].encode("utf-8"))})

    return {
        "id": str(ver.id),
        "capability_id": str(ver.capability_id),
        "version": ver.version,
        "status": ver.status,
        "package_fingerprint": ver.package_fingerprint,
        "compatibility_level": ver.compatibility_level,
        "workflow_snapshot": ver.workflow_snapshot,
        "input_schema": ver.input_schema,
        "output_schema": ver.output_schema,
        "created_source": ver.created_source,
        "created_at": ver.created_at,
        "validation_report": pkg.validation_report if pkg else None,
        "files": files_list,
    }


# --- External Agent Token 管理 API ---


class CreateExternalTokenRequest(BaseModel):
    name: str
    scopes: list[str]
    ttlDays: int | None = None


@router.post(
    "/projects/{projectId}/external-tokens",
    summary="创建 External Agent 用户委托 Access Token",
)
def create_external_token(
    projectId: uuid.UUID,
    body: CreateExternalTokenRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(AGENT_MANAGE)),
) -> dict[str, Any]:
    token_obj, raw_token = ExternalAgentTokenService.create_token(
        db=db,
        name=body.name,
        project_id=projectId,
        user_id=user.id,
        scopes=body.scopes,
        ttl_days=body.ttlDays,
    )
    return {
        "id": str(token_obj.id),
        "name": token_obj.name,
        "tokenPrefix": token_obj.token_prefix,
        "rawToken": raw_token,
        "projectId": str(token_obj.project_id),
        "scopes": token_obj.scopes,
        "expiresAt": token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        "createdAt": token_obj.created_at.isoformat(),
    }


@router.get(
    "/projects/{projectId}/external-tokens",
    summary="获取项目的 External Agent Token 列表",
)
def list_external_tokens(
    projectId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(AGENT_MANAGE)),
) -> dict[str, Any]:
    tokens = ExternalAgentTokenService.list_project_tokens(db, projectId)
    return {
        "tokens": [
            {
                "id": str(t.id),
                "name": t.name,
                "tokenPrefix": t.token_prefix,
                "createdByUserId": str(t.created_by_user_id),
                "scopes": t.scopes,
                "expiresAt": t.expires_at.isoformat() if t.expires_at else None,
                "revokedAt": t.revoked_at.isoformat() if t.revoked_at else None,
                "lastUsedAt": t.last_used_at.isoformat() if t.last_used_at else None,
                "createdAt": t.created_at.isoformat(),
            }
            for t in tokens
        ]
    }


@router.delete(
    "/projects/{projectId}/external-tokens/{tokenId}",
    summary="撤销 External Agent Token",
)
def revoke_external_token(
    projectId: uuid.UUID,
    tokenId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(AGENT_MANAGE)),
) -> dict[str, Any]:
    ExternalAgentTokenService.revoke_token(db, tokenId, projectId)
    return {"message": "Token 已成功撤销"}
