import uuid
import pytest
from datetime import UTC, datetime
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import CodeRepository, RepositorySyncJob
from testweave.modules.repositories.sync import RepositorySyncManager
from testweave.modules.repositories.matcher import MatcherService
from testweave.modules.users.service import UserService
from testweave.modules.projects.service import ProjectService


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

    # 1. 模拟第一个 Worker 领取并执行 (由于我们没有 Mock git 连接，执行 sync 会抛出异常，触发 FAILED)
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
