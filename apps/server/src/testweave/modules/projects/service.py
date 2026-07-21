import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from testweave.db.models import Project, ProjectMember, User
from testweave.modules.audit.service import AuditService


class ProjectService:
    @staticmethod
    def create_project(
        db: Session,
        *,
        key: str,
        name: str,
        description: str | None = None,
        timezone_str: str = "UTC",
        owner_id: uuid.UUID,
        request_id: str,
    ) -> Project:
        """创建项目，并把所有者设为项目管理员 (事务内原子操作)"""
        # 校验项目 Key 唯一性
        stmt = select(Project).where(Project.key == key)
        if db.scalar(stmt):
            raise ValueError("项目 Key 已存在")

        project = Project(
            key=key,
            name=name,
            description=description,
            status="active",
            timezone=timezone_str,
            owner_id=owner_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(project)
        db.flush()  # 获得项目 ID

        # 将创建者添加为项目管理员
        member = ProjectMember(
            project_id=project.id,
            user_id=owner_id,
            role_id="project_admin",
            joined_at=datetime.now(UTC),
        )
        db.add(member)

        # 记录审计事件
        AuditService.log_event(
            db,
            project_id=project.id,
            actor_id=owner_id,
            action="project_create",
            object_type="project",
            object_id=str(project.id),
            summary=f"创建项目 '{name}' (Key: {key})",
            request_id=request_id,
        )

        return project

    @staticmethod
    def list_projects(
        db: Session,
        *,
        user_id: uuid.UUID,
        is_system_admin: bool = False,
    ) -> list[dict[str, Any]]:
        """获取可见项目列表。普通用户仅能看到所属项目；系统管理员可以看到所有项目"""
        if is_system_admin:
            # 获取所有项目
            stmt = select(Project).order_by(desc(Project.created_at))
            projects = db.scalars(stmt).all()
        else:
            # 获取当前用户所属项目
            stmt = (
                select(Project)
                .join(ProjectMember, Project.id == ProjectMember.project_id)
                .where(ProjectMember.user_id == user_id)
                .order_by(desc(Project.created_at))
            )
            projects = db.scalars(stmt).all()

        result = []
        for p in projects:
            # 查询当前用户在该项目中的角色
            member_stmt = select(ProjectMember).where(
                and_(ProjectMember.project_id == p.id, ProjectMember.user_id == user_id)
            )
            member = db.scalar(member_stmt)
            role_id = member.role_id if member else ("system_admin" if is_system_admin else None)

            result.append(
                {
                    "id": p.id,
                    "key": p.key,
                    "name": p.name,
                    "description": p.description,
                    "status": p.status,
                    "timezone": p.timezone,
                    "role_id": role_id,
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                }
            )
        return result

    @staticmethod
    def get_project_by_id(db: Session, project_id: uuid.UUID) -> Project | None:
        """通过 ID 查询项目"""
        return db.get(Project, project_id)

    @staticmethod
    def update_project(
        db: Session,
        *,
        project_id: uuid.UUID,
        name: str,
        description: str | None,
        timezone_str: str,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> Project:
        """修改项目基本信息"""
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        if project.status == "archived":
            raise ValueError("归档项目不可修改")

        project.name = name
        project.description = description
        project.timezone = timezone_str
        project.updated_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            project_id=project.id,
            actor_id=actor_id,
            action="project_update",
            object_type="project",
            object_id=str(project.id),
            summary=f"修改项目信息：'{name}'",
            request_id=request_id,
        )
        return project

    @staticmethod
    def archive_project(
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> Project:
        """归档项目 (置为只读)"""
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        project.status = "archived"
        project.updated_at = datetime.now(UTC)

        AuditService.log_event(
            db,
            project_id=project.id,
            actor_id=actor_id,
            action="project_archive",
            object_type="project",
            object_id=str(project.id),
            summary="归档项目",
            request_id=request_id,
        )
        return project

    @staticmethod
    def get_member(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember | None:
        """获取项目成员关联关系"""
        stmt = select(ProjectMember).where(
            and_(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        )
        return db.scalar(stmt)

    @staticmethod
    def list_members(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """获取项目成员列表"""
        stmt = (
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.joined_at)
        )
        members = db.execute(stmt).all()
        return [
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name,
                "role_id": member.role_id,
                "status": user.status,
                "joined_at": member.joined_at,
            }
            for member, user in members
        ]

    @staticmethod
    def add_member(
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: str,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> ProjectMember:
        """添加项目成员"""
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        if project.status == "archived":
            raise ValueError("归档项目无法添加成员")

        # 校验用户是否存在
        user = db.get(User, user_id)
        if not user or user.status != "active":
            raise ValueError("用户不存在或已被停用")

        # 检查是否已经是成员
        existing = ProjectService.get_member(db, project_id, user_id)
        if existing:
            raise ValueError("该用户已是项目成员")

        # 校验角色合法性
        if role_id not in ["project_admin", "test_lead", "test_member"]:
            raise ValueError("非法项目角色")

        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role_id=role_id,
            joined_at=datetime.now(UTC),
        )
        db.add(member)

        # 记录审计事件
        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="member_add",
            object_type="user",
            object_id=str(user_id),
            summary=f"添加成员 '{user.username}'，角色分配为 '{role_id}'",
            request_id=request_id,
        )
        return member

    @staticmethod
    def _is_last_project_admin(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """判断是否是该项目最后一名有效的项目管理员 (用 SELECT FOR UPDATE 悲观锁保证并发安全)"""
        # 查询该项目下 role_id 为 project_admin 且用户状态为 active 的成员，并加行级锁
        stmt = (
            select(ProjectMember)
            .join(User, ProjectMember.user_id == User.id)
            .where(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role_id == "project_admin",
                    User.status == "active",
                )
            )
            .with_for_update()  # 开启行级锁
        )
        admins = db.scalars(stmt).all()
        count = len(admins)

        if count <= 1:
            # 如果数量 <= 1，且当前操作人就是该 project_admin，则是最后一名
            current_is_admin_stmt = select(ProjectMember).where(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.role_id == "project_admin",
                )
            )
            if db.scalar(current_is_admin_stmt):
                return True
        return False

    @staticmethod
    def update_member_role(
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: str,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> ProjectMember:
        """修改项目成员角色"""
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        if project.status == "archived":
            raise ValueError("归档项目无法修改成员")

        member = ProjectService.get_member(db, project_id, user_id)
        if not member:
            raise ValueError("成员不存在")

        if role_id not in ["project_admin", "test_lead", "test_member"]:
            raise ValueError("非法项目角色")

        # 保护最后一名项目管理员：如果该成员目前是 project_admin 且新角色不是 project_admin
        if (
            member.role_id == "project_admin"
            and role_id != "project_admin"
            and ProjectService._is_last_project_admin(db, project_id, user_id)
        ):
            raise ValueError("项目必须保留至少一名有效的项目管理员")

        old_role = member.role_id
        member.role_id = role_id

        user = db.get(User, user_id)
        username = user.username if user else str(user_id)

        # 记录审计事件
        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="member_update_role",
            object_type="user",
            object_id=str(user_id),
            summary=f"变更成员 '{username}' 角色：由 '{old_role}' 变为 '{role_id}'",
            request_id=request_id,
        )
        return member

    @staticmethod
    def remove_member(
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> None:
        """移除项目成员"""
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        if project.status == "archived":
            raise ValueError("归档项目无法移除成员")

        member = ProjectService.get_member(db, project_id, user_id)
        if not member:
            raise ValueError("成员不存在")

        # 保护最后一名项目管理员：如果要被移除的是 project_admin
        if member.role_id == "project_admin" and ProjectService._is_last_project_admin(
            db, project_id, user_id
        ):
            raise ValueError("项目必须保留至少一名有效的项目管理员")

        user = db.get(User, user_id)
        username = user.username if user else str(user_id)

        db.delete(member)

        # 记录审计事件
        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="member_remove",
            object_type="user",
            object_id=str(user_id),
            summary=f"移除了项目成员 '{username}'",
            request_id=request_id,
        )
