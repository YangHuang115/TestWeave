import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import AISkill, AISkillPackage, AISkillVersion, User
from testweave.modules.ai_skill.service import SkillRegistryService
from testweave.shared.permissions import AGENT_MANAGE, PROJECT_READ

router = APIRouter()


def _get_project_skill(
    db: Session,
    *,
    project_id: uuid.UUID,
    skill_id: uuid.UUID,
) -> AISkill:
    skill = db.scalar(
        select(AISkill).where(
            AISkill.id == skill_id,
            AISkill.project_id == project_id,
        )
    )
    if skill is None:
        raise AppError(
            code="SKILL_NOT_FOUND",
            message="Skill 不存在或不属于当前项目",
            status_code=404,
        )
    return skill


def _serialize_skill(skill: AISkill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "projectId": str(skill.project_id),
        "maintainerId": str(skill.maintainer_id) if skill.maintainer_id else None,
        "code": skill.code,
        "name": skill.name,
        "description": skill.description,
        "status": skill.status,
        "currentPublishedVersionId": (
            str(skill.current_published_version_id) if skill.current_published_version_id else None
        ),
        "createdAt": skill.created_at,
        "updatedAt": skill.updated_at,
    }


def _serialize_version(version: AISkillVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "skillId": str(version.skill_id),
        "version": version.version,
        "status": version.status,
        "packageFingerprint": version.package_fingerprint,
        "modelPolicy": version.model_policy,
        "allowedTools": version.allowed_tools,
        "requiredPermissions": version.required_permissions,
        "sideEffectLevel": version.side_effect_level,
        "createdSource": version.created_source,
        "createdBy": str(version.created_by) if version.created_by else None,
        "publishedAt": version.published_at,
        "createdAt": version.created_at,
    }


@router.get(
    "/projects/{projectId}/skills",
    summary="获取项目已注册的 AI Skill 列表",
)
async def list_project_skills(
    projectId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> dict[str, Any]:
    skills = list(
        db.scalars(
            select(AISkill).where(AISkill.project_id == projectId).order_by(AISkill.code.asc())
        ).all()
    )
    return {"items": [_serialize_skill(skill) for skill in skills]}


@router.get(
    "/projects/{projectId}/skills/{skillId}",
    summary="获取项目 AI Skill 详情",
)
async def get_project_skill(
    projectId: uuid.UUID,
    skillId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> dict[str, Any]:
    return _serialize_skill(_get_project_skill(db, project_id=projectId, skill_id=skillId))


@router.get(
    "/projects/{projectId}/skills/{skillId}/versions",
    summary="获取项目 AI Skill 版本列表",
)
async def list_project_skill_versions(
    projectId: uuid.UUID,
    skillId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> dict[str, Any]:
    skill = _get_project_skill(db, project_id=projectId, skill_id=skillId)
    versions = list(
        db.scalars(
            select(AISkillVersion)
            .where(AISkillVersion.skill_id == skill.id)
            .order_by(AISkillVersion.created_at.desc())
        ).all()
    )
    return {"items": [_serialize_version(version) for version in versions]}


@router.get(
    "/projects/{projectId}/skills/{skillId}/versions/{versionId}",
    summary="获取项目 AI Skill 版本详情",
)
async def get_project_skill_version(
    projectId: uuid.UUID,
    skillId: uuid.UUID,
    versionId: uuid.UUID,
    db: Session = Depends(get_db),
    _permission: Any = Depends(require_project_permission(PROJECT_READ)),
) -> dict[str, Any]:
    skill = _get_project_skill(db, project_id=projectId, skill_id=skillId)
    version = db.scalar(
        select(AISkillVersion).where(
            AISkillVersion.id == versionId,
            AISkillVersion.skill_id == skill.id,
        )
    )
    if version is None:
        raise AppError(
            code="SKILL_VERSION_NOT_FOUND",
            message="Skill 版本不存在",
            status_code=404,
        )
    package = db.scalar(select(AISkillPackage).where(AISkillPackage.skill_version_id == version.id))
    result = _serialize_version(version)
    result.update(
        {
            "manifest": version.manifest_snapshot,
            "inputSchema": version.input_schema,
            "outputSchema": version.output_schema,
            "validationReport": package.validation_report if package else None,
            "files": sorted(package.files_snapshot) if package else [],
        }
    )
    return result


@router.post(
    "/projects/{projectId}/skills/{skillId}/versions/{versionId}/publish",
    summary="发布项目 AI Skill 版本",
)
async def publish_project_skill_version(
    projectId: uuid.UUID,
    skillId: uuid.UUID,
    versionId: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _permission: Any = Depends(require_project_permission(AGENT_MANAGE)),
) -> dict[str, Any]:
    return SkillRegistryService.publish_version(
        db=db,
        project_id=projectId,
        skill_id=skillId,
        version_id=versionId,
        actor_id=user.id,
        request_id=request.state.request_id,
    )
