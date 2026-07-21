import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import CodeRepository
from testweave.infrastructure.git import GitClient
from testweave.modules.audit.service import AuditService
from testweave.shared.crypto import CryptoService


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
        normalized_remote_url = GitClient.validate_remote_url_syntax(remote_url)
        normalized_auth_type = GitClient.validate_auth_type(auth_type)
        normalized_main_branch = GitClient.validate_main_branch(main_branch)
        repo = RepositoryService.get_repository_by_project_id(db, project_id)
        endpoint_unchanged = bool(
            repo
            and repo.remote_url.strip() == normalized_remote_url
            and repo.auth_type == normalized_auth_type
        )

        # 1. 验证 Git 网络及凭证连接性 (如果 enabled)
        if enabled:
            test_cred = credential_content
            if not (test_cred and test_cred.strip()):
                test_cred = None
                if endpoint_unchanged and repo and repo.credential_ref:
                    test_cred = CryptoService.decrypt(repo.credential_ref)
                elif normalized_auth_type != "NONE":
                    raise AppError(
                        code="REPOSITORY_CREDENTIAL_REQUIRED",
                        message="仓库地址或认证方式变更后必须重新提供凭证",
                        status_code=400,
                    )

            RepositoryService.verify_connection(
                remote_url=normalized_remote_url,
                auth_type=normalized_auth_type,
                credential_content=test_cred,
                main_branch=normalized_main_branch,
            )

        # 2. 如果存在则更新
        if repo:
            if row_version is None or repo.row_version != row_version:
                raise AppError(
                    code="OPTIMISTIC_LOCK_CONFLICT",
                    message="代码仓库配置已被其他用户更新，请刷新重试",
                    status_code=409,
                )

            repo.name = name.strip()
            repo.remote_url = normalized_remote_url
            repo.auth_type = normalized_auth_type
            repo.main_branch = normalized_main_branch
            repo.enabled = enabled
            repo.row_version += 1
            repo.updated_at = datetime.now(UTC)

            # 凭证只与原地址和认证方式绑定；端点变化时不得静默复用旧凭证。
            if credential_content and credential_content.strip():
                repo.credential_ref = CryptoService.encrypt(credential_content)
            elif not endpoint_unchanged or credential_content is not None:
                repo.credential_ref = None

            action = "UPDATE"
        else:
            # 3. 不存在则创建
            encrypted_ref = (
                CryptoService.encrypt(credential_content)
                if credential_content and credential_content.strip()
                else None
            )
            repo = CodeRepository(
                project_id=uuid.UUID(str(project_id)),
                repository_type="GIT",
                provider_type="GENERIC",
                name=name.strip(),
                remote_url=normalized_remote_url,
                auth_type=normalized_auth_type,
                credential_ref=encrypted_ref,
                main_branch=normalized_main_branch,
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
