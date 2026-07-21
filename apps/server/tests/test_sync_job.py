import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import CodeRepository
from testweave.modules.projects.service import ProjectService
from testweave.modules.repositories.matcher import MatcherService
from testweave.modules.repositories.service import RepositoryService
from testweave.modules.repositories.sync import RepositorySyncManager
from testweave.modules.users.service import UserService

PUBLIC_ADDRESS_INFO = [
    (2, 1, 6, "", ("93.184.216.34", 443)),
]


class StopSync(Exception):
    pass


def test_repository_update_does_not_reuse_credential_for_new_remote() -> None:
    project_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        remote_url="https://old.example/org/repo.git",
        auth_type="HTTP_TOKEN",
        credential_ref="encrypted-old-token",
        row_version=1,
    )
    db = MagicMock()
    db.scalar.return_value = existing

    with (
        patch("testweave.modules.repositories.service.CryptoService.decrypt") as mock_decrypt,
        patch.object(RepositoryService, "verify_connection") as mock_verify,
        pytest.raises(AppError) as exc_info,
    ):
        RepositoryService.create_or_update_repository(
            db,
            project_id=str(project_id),
            name="Moved repository",
            remote_url="https://new.example/org/repo.git",
            auth_type="HTTP_TOKEN",
            credential_content=None,
            main_branch="main",
            enabled=True,
            row_version=1,
            actor_id=str(actor_id),
            request_id="req-credential-boundary",
        )

    assert exc_info.value.code == "REPOSITORY_CREDENTIAL_REQUIRED"
    mock_decrypt.assert_not_called()
    mock_verify.assert_not_called()


def test_disabled_repository_rejects_credential_bearing_remote_url() -> None:
    db = MagicMock()
    db.scalar.return_value = None

    with pytest.raises(AppError) as exc_info:
        RepositoryService.create_or_update_repository(
            db,
            project_id=str(uuid.uuid4()),
            name="Unsafe disabled repository",
            remote_url="https://user:secret@example.com/org/repo.git",
            auth_type="NONE",
            credential_content=None,
            main_branch="main",
            enabled=False,
            row_version=None,
            actor_id=str(uuid.uuid4()),
            request_id="req-disabled-url",
        )

    assert exc_info.value.code == "INVALID_REPOSITORY_URL"
    db.add.assert_not_called()


def test_matcher_extract_tokens() -> None:
    # 验证单号提取和边界过滤
    msg1 = "[REQ-1001] fix alignment issue"
    tokens1 = MatcherService.extract_requirement_tokens(msg1)
    assert tokens1 == ["req-1001"]

    msg2 = "fix REQ-1001 and REQ-1002"
    tokens2 = MatcherService.extract_requirement_tokens(msg2)
    assert sorted(tokens2) == ["req-1001", "req-1002"]

    msg3 = "modify REQ-10011 but don't match REQ"
    tokens3 = MatcherService.extract_requirement_tokens(msg3)
    assert "req-1001" not in tokens3
    assert tokens3 == ["req-10011"]


def test_sync_job_lease_lock_and_attempt(db: Session) -> None:
    # 建立测试数据
    user = UserService.create_user(
        db,
        username="syncuser",
        email="su@tw.com",
        display_name="Sync User",
        password="pwd",
    )
    db.commit()
    proj = ProjectService.create_project(
        db,
        key="SNCPROJ",
        name="Sync Project",
        owner_id=user.id,
        request_id="req-s",
    )
    db.commit()

    repo = CodeRepository(
        project_id=proj.id,
        repository_type="GIT",
        provider_type="GENERIC",
        name="Sync Repo",
        remote_url="git@github.com:example/test.git",
        auth_type="NONE",
        main_branch="main",
        enabled=True,
    )
    db.add(repo)
    db.commit()

    # 创建一个 PENDING 任务
    job1 = RepositorySyncManager.create_sync_job(db, str(proj.id), str(repo.id), str(user.id))
    db.commit()

    assert job1.status == "PENDING"
    assert job1.attempt == 0

    # 第一个 Worker 领取并执行；真实 Git 连接失败后任务应进入 FAILED。
    # 我们正好可以通过这个失败结果验证：失败后 attempt 自增、状态设为 FAILED 且退避 30s 重新就绪！
    count1 = RepositorySyncManager.poll_and_execute_jobs(db, "worker-1")
    assert count1 == 1

    db.refresh(job1)
    assert job1.status == "FAILED"
    assert job1.attempt == 1
    assert job1.error_code is not None
    assert job1.available_at.replace(tzinfo=None) > datetime.now(UTC).replace(tzinfo=None)

    # 2. 模拟第二个 Worker 试图立即领取（由于失败退避了 30s，目前不可用，应该领取不到）
    count2 = RepositorySyncManager.poll_and_execute_jobs(db, "worker-2")
    assert count2 == 0


def test_sync_clone_keeps_http_token_out_of_remote_url_and_argv(tmp_path: Path) -> None:
    token = "synthetic-sync-token-REQ-10002"
    repository_id = uuid.uuid4()
    repo = SimpleNamespace(
        id=repository_id,
        enabled=True,
        remote_url="https://example.com/org/repo.git",
        auth_type="HTTP_TOKEN",
        credential_ref="encrypted-token",
        main_branch="main",
        last_synced_head_sha=None,
    )
    db = MagicMock()
    db.get.return_value = repo
    commands: list[list[str]] = []

    def stop_after_clone(
        args: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        raise StopSync

    with (
        patch("testweave.modules.repositories.sync.CryptoService.decrypt", return_value=token),
        patch(
            "testweave.infrastructure.git.socket.getaddrinfo",
            return_value=PUBLIC_ADDRESS_INFO,
        ),
        patch(
            "testweave.modules.repositories.sync.GitClient.run_git_command",
            side_effect=stop_after_clone,
        ),
        patch("testweave.modules.repositories.sync.os.getcwd", return_value=str(tmp_path)),
        pytest.raises(StopSync),
    ):
        RepositorySyncManager.sync_repository(
            db,
            repository_id=str(repository_id),
            job_id=str(uuid.uuid4()),
        )

    assert commands[0][0:3] == ["git", "clone", "--mirror"]
    assert commands[0][3] == repo.remote_url
    assert token not in repr(commands)


def test_sync_existing_mirror_scrubs_origin_before_fetch(tmp_path: Path) -> None:
    token = "synthetic-existing-token-REQ-10002"
    repository_id = uuid.uuid4()
    repo = SimpleNamespace(
        id=repository_id,
        enabled=True,
        remote_url="https://example.com/org/repo.git",
        auth_type="HTTP_TOKEN",
        credential_ref="encrypted-token",
        main_branch="main",
        last_synced_head_sha=None,
    )
    db = MagicMock()
    db.get.return_value = repo
    data_dir = tmp_path / "data"
    local_dir = data_dir / "git_clones" / f"{repository_id}.git"
    local_dir.mkdir(parents=True)
    commands: list[list[str]] = []

    def stop_after_fetch(
        args: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        if len(commands) == 2:
            raise StopSync
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("testweave.modules.repositories.sync.CryptoService.decrypt", return_value=token),
        patch(
            "testweave.infrastructure.git.socket.getaddrinfo",
            return_value=PUBLIC_ADDRESS_INFO,
        ),
        patch(
            "testweave.modules.repositories.sync.GitClient.run_git_command",
            side_effect=stop_after_fetch,
        ),
        patch("testweave.modules.repositories.sync.os.getcwd", return_value=str(tmp_path)),
        pytest.raises(StopSync),
    ):
        RepositorySyncManager.sync_repository(
            db,
            repository_id=str(repository_id),
            job_id=str(uuid.uuid4()),
        )

    assert commands[0] == [
        "git",
        f"--git-dir={local_dir}",
        "remote",
        "set-url",
        "origin",
        repo.remote_url,
    ]
    assert commands[1] == [
        "git",
        f"--git-dir={local_dir}",
        "fetch",
        "origin",
        "--prune",
    ]
    assert token not in repr(commands)
