import uuid
import unicodedata
from datetime import UTC, datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from testweave.core.errors import AppError
from testweave.db.models import (
    Requirement,
    Version,
    VersionRequirement,
    RequirementCommitLink,
)
from testweave.modules.audit.service import AuditService


def normalize_requirement_no(no: str) -> str:
    """需求单号规范化: NFKC + Strip + Casefold"""
    return unicodedata.normalize("NFKC", no).strip().casefold()


class RequirementService:
    @staticmethod
    def get_requirement_by_id(db: Session, project_id: str, requirement_id: str) -> Requirement:
        stmt = select(Requirement).where(
            Requirement.id == uuid.UUID(str(requirement_id)),
            Requirement.project_id == uuid.UUID(str(project_id))
        )
        req = db.scalar(stmt)
        if not req:
            raise AppError(code="REQUIREMENT_NOT_FOUND", message="需求不存在或无权限访问", status_code=404)
        return req

    @staticmethod
    def generate_next_requirement_no(db: Session, project_id: str) -> str:
        """根据项目内已有需求自动计算生成下一个 REQ-XXXXX 单号"""
        stmt = select(Requirement.requirement_no).where(
            Requirement.project_id == uuid.UUID(str(project_id))
        )
        existing_nos = db.scalars(stmt).all()

        import re
        max_num = 10000  # 默认起始为 10001 (10000 + 1)
        pattern = re.compile(r'(?i)^REQ-(\d+)$')
        for no in existing_nos:
            match = pattern.match(no.strip())
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

        return f"REQ-{max_num + 1}"

    @staticmethod
    def create_requirement(
        db: Session,
        project_id: str,
        requirement_no: str | None,
        title: str,
        description: str | None,
        priority: str,
        owner_id: str | None,
        actor_id: str,
        request_id: str,
    ) -> Requirement:
        if not requirement_no or not requirement_no.strip():
            requirement_no = RequirementService.generate_next_requirement_no(db, project_id)

        normalized_no = normalize_requirement_no(requirement_no)

        # 校验项目内唯一性
        conflict_stmt = select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.requirement_no_normalized == normalized_no
        )
        if db.scalar(conflict_stmt):
            raise AppError(
                code="REQUIREMENT_KEY_CONFLICT",
                message=f"需求单号 {requirement_no} 在该项目内已存在",
                status_code=400,
            )

        req = Requirement(
            project_id=project_id,
            requirement_no=requirement_no.strip(),
            requirement_no_normalized=normalized_no,
            title=title.strip(),
            description=description,
            priority=priority,
            status="DRAFT",
            owner_id=owner_id,
            row_version=1,
        )
        db.add(req)
        db.flush()

        # 自动扫描绑定已在库中的 Git Commit
        from testweave.modules.repositories.matcher import MatcherService
        try:
            MatcherService.match_single_requirement(db, project_id, req)
        except Exception:
            pass

        # 记录审计日志
        AuditService.log_event(
            db,
            action="requirement.created",
            object_type="Requirement",
            object_id=str(req.id),
            summary=f"创建需求 '{req.title}' (单号: {req.requirement_no})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
        return req

    @staticmethod
    def update_requirement(
        db: Session,
        project_id: str,
        requirement_id: str,
        requirement_no: str,
        title: str,
        description: str | None,
        priority: str,
        owner_id: str | None,
        status: str,
        expected_row_version: int,
        actor_id: str,
        request_id: str,
        force_change_no: bool = False,
    ) -> Requirement:
        req = RequirementService.get_requirement_by_id(db, project_id, requirement_id)

        # 乐观锁校验
        if req.row_version != expected_row_version:
            raise AppError(
                code="OPTIMISTIC_LOCK_CONFLICT",
                message="当前需求已被其他用户修改，请刷新后重试",
                status_code=409,
            )

        new_no_normalized = normalize_requirement_no(requirement_no)
        old_no_normalized = req.requirement_no_normalized

        # 如果单号修改了
        if new_no_normalized != old_no_normalized:
            # 1. 检查新单号冲突
            conflict_stmt = select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.requirement_no_normalized == new_no_normalized,
                Requirement.id != requirement_id
            )
            if db.scalar(conflict_stmt):
                raise AppError(
                    code="REQUIREMENT_KEY_CONFLICT",
                    message=f"需求单号 {requirement_no} 在该项目内已存在",
                    status_code=400,
                )

            # 2. 检查是否有代码关联提交
            commit_link_stmt = select(RequirementCommitLink).where(
                RequirementCommitLink.requirement_id == requirement_id
            )
            has_commits = db.scalar(commit_link_stmt) is not None
            if has_commits and not force_change_no:
                raise AppError(
                    code="REQUIREMENT_HAS_COMMITS",
                    message="该需求已有关联的代码提交。修改单号将导致已有代码关联失效。请确认是否强制修改？",
                    status_code=400,
                )

            if has_commits and force_change_no:
                # 强制修改单号，解绑已有的 commit 链接 (后续重新扫描匹配)
                db.query(RequirementCommitLink).filter(
                    RequirementCommitLink.requirement_id == requirement_id
                ).delete()

        req.requirement_no = requirement_no.strip()
        req.requirement_no_normalized = new_no_normalized
        req.title = title.strip()
        req.description = description
        req.priority = priority
        req.owner_id = owner_id
        req.status = status
        req.row_version += 1
        req.updated_at = datetime.now(UTC)

        db.flush()

        # 如果单号发生变化，触发重新寻找并绑定匹配已有 Git Commits
        if new_no_normalized != old_no_normalized:
            from testweave.modules.repositories.matcher import MatcherService
            try:
                MatcherService.match_single_requirement(db, project_id, req)
            except Exception:
                pass

        AuditService.log_event(
            db,
            action="requirement.updated",
            object_type="Requirement",
            object_id=str(req.id),
            summary=f"更新需求 '{req.title}' (单号: {req.requirement_no})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
        return req

    @staticmethod
    def associate_to_version(
        db: Session,
        project_id: str,
        requirement_id: str,
        version_id: str,
        actor_id: str,
        request_id: str,
    ) -> None:
        # 验证需求存在性
        req = RequirementService.get_requirement_by_id(db, project_id, requirement_id)
        
        # 验证版本存在性
        version_stmt = select(Version).where(Version.id == version_id, Version.project_id == project_id)
        version = db.scalar(version_stmt)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="版本不存在", status_code=404)

        # 归档版本禁止修改需求范围
        if version.status == "ARCHIVED":
            raise AppError(code="VERSION_ARCHIVED", message="版本已归档，不允许修改其需求范围", status_code=400)

        # 检查是否已关联
        link_stmt = select(VersionRequirement).where(
            VersionRequirement.version_id == version_id,
            VersionRequirement.requirement_id == requirement_id
        )
        if db.scalar(link_stmt):
            return

        link = VersionRequirement(version_id=version_id, requirement_id=requirement_id)
        db.add(link)
        db.flush()

        AuditService.log_event(
            db,
            action="version.associated_requirement",
            object_type="Version",
            object_id=str(version_id),
            summary=f"版本 '{version.name}' 关联了需求 '{req.title}' (单号: {req.requirement_no})",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

    @staticmethod
    def dissociate_from_version(
        db: Session,
        project_id: str,
        requirement_id: str,
        version_id: str,
        actor_id: str,
        request_id: str,
    ) -> None:
        # 验证需求
        req = RequirementService.get_requirement_by_id(db, project_id, requirement_id)

        # 验证版本
        version_stmt = select(Version).where(Version.id == version_id, Version.project_id == project_id)
        version = db.scalar(version_stmt)
        if not version:
            raise AppError(code="VERSION_NOT_FOUND", message="版本不存在", status_code=404)

        # 归档版本禁止解绑需求
        if version.status == "ARCHIVED":
            raise AppError(code="VERSION_ARCHIVED", message="版本已归档，不允许修改其需求范围", status_code=400)

        # 删除关联
        db.query(VersionRequirement).filter(
            VersionRequirement.version_id == version_id,
            VersionRequirement.requirement_id == requirement_id
        ).delete()
        db.flush()

        AuditService.log_event(
            db,
            action="version.dissociated_requirement",
            object_type="Version",
            object_id=str(version_id),
            summary=f"版本 '{version.name}' 解除了与需求 '{req.title}' (单号: {req.requirement_no}) 的关联",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )
