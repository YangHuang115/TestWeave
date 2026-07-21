import uuid
from datetime import UTC, datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from testweave.core.errors import AppError
from testweave.db.models import CodeRepository
from testweave.infrastructure.git import GitClient
from testweave.shared.crypto import CryptoService
from testweave.modules.audit.service import AuditService


class RepositoryService:
    @staticmethod
    def get_repository_by_project_id(db: Session, project_id: str) -> CodeRepository | None:
        stmt = select(CodeRepository).where(CodeRepository.project_id == uuid.UUID(str(project_id)))
        return db.scalar(stmt)

    @staticmethod
    def verify_connection(
        remote_url: str,
        auth_type: str,
        credential_content: str | None = None,
        main_branch: str = "main",
    ) -> None:
        GitClient.verify_connection(
            remote_url=remote_url,
            auth_type=auth_type,
            credential_content=credential_content,
            main_branch=main_branch,
        )

    @staticmethod
    def create_or_update_repository(
        db: Session,
        project_id: str,
        name: str,
        remote_url: str,
        auth_type: str,
        credential_content: str | None,
        main_branch: str,
        enabled: bool,
        row_version: int | None,
        actor_id: str,
        request_id: str,
    ) -> CodeRepository:
        # 1. 验证 Git 网络及凭证连接性 (如果 enabled)
        if enabled:
            # 如果是更新且没有传新凭证，需要读取已有的老凭证做测试连接
            test_cred = credential_content
            if test_cred is None:
                existing = RepositoryService.get_repository_by_project_id(db, project_id)
                if existing and existing.credential_ref:
                    test_cred = CryptoService.decrypt(existing.credential_ref)

            RepositoryService.verify_connection(
                remote_url=remote_url,
                auth_type=auth_type,
                credential_content=test_cred,
                main_branch=main_branch,
            )

        repo = RepositoryService.get_repository_by_project_id(db, project_id)

        # 2. 如果存在则更新
        if repo:
            if row_version is None or repo.row_version != row_version:
                raise AppError(
                    code="OPTIMISTIC_LOCK_CONFLICT",
                    message="代码仓库配置已被其他用户更新，请刷新重试",
                    status_code=409,
                )

            repo.name = name.strip()
            repo.remote_url = remote_url.strip()
            repo.auth_type = auth_type
            repo.main_branch = main_branch.strip()
            repo.enabled = enabled
            repo.row_version += 1
            repo.updated_at = datetime.now(UTC)

            # 仅在传入新凭证时加密更新，未传则保持原凭证不变
            if credential_content is not None:
                repo.credential_ref = CryptoService.encrypt(credential_content)

            action = "UPDATE"
        else:
            # 3. 不存在则创建
            encrypted_ref = CryptoService.encrypt(credential_content) if credential_content else None
            repo = CodeRepository(
                project_id=uuid.UUID(str(project_id)),
                repository_type="GIT",
                provider_type="GENERIC",
                name=name.strip(),
                remote_url=remote_url.strip(),
                auth_type=auth_type,
                credential_ref=encrypted_ref,
                main_branch=main_branch.strip(),
                enabled=enabled,
                sync_status="NOT_SYNCED",
                row_version=1,
            )
            db.add(repo)
            action = "CREATE"

        db.flush()

        # 4. 记录审计
        AuditService.log_event(
            db,
            action=f"repository.{action.lower()}",
            object_type="CodeRepository",
            object_id=str(repo.id),
            summary=f"{'创建' if action == 'CREATE' else '更新'}了代码仓库配置 '{name}'",
            request_id=request_id,
            project_id=uuid.UUID(str(project_id)),
            actor_id=uuid.UUID(str(actor_id)),
        )

        return repo
