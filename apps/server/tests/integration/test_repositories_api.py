import uuid
from datetime import datetime
import pytest
from unittest.mock import patch
from typing import Any
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.users.service import UserService
from testweave.modules.projects.service import ProjectService

pytestmark = pytest.mark.integration


@pytest.fixture
async def repo_integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    admin_user = UserService.create_user(
        session, username="repoapiadmin", email="rpa@tw.com", display_name="Repo API Admin", password="pwd"
    )
    guest_user = UserService.create_user(
        session, username="repoapiguest", email="rpg@tw.com", display_name="Repo API Guest", password="pwd"
    )
    session.commit()

    project = ProjectService.create_project(
        session, key="REPOAPIP", name="Repo API Project", owner_id=admin_user.id, request_id="repo-p"
    )
    session.commit()

    # 登录并获取 cookies 与 csrf 令牌
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "repoapiadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    res_guest = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "repoapiguest", "password": "pwd"}
    )
    cookies_guest = res_guest.cookies
    csrf_guest = cookies_guest.get("xsrf_token")

    return {
        "project": project,
        "admin_session": {"cookies": cookies_admin, "headers": {"X-CSRF-Token": csrf_admin}},
        "guest_session": {"cookies": cookies_guest, "headers": {"X-CSRF-Token": csrf_guest}},
    }


@pytest.mark.anyio
async def test_repository_api_lifecycle(
    client: AsyncClient, session: Session, repo_integration_context: dict[str, Any]
) -> None:
    project = repo_integration_context["project"]
    admin_session = repo_integration_context["admin_session"]
    guest_session = repo_integration_context["guest_session"]

    # 1. 初始获取配置：应返回 404 REPOSITORY_NOT_FOUND
    res_get_init = await client.get(
        f"/api/v1/projects/{project.id}/repository",
        **admin_session,
    )
    assert res_get_init.status_code == 404

    # 2. 项目隔离测试：非项目成员访问配置返回 403
    res_guest_get = await client.get(
        f"/api/v1/projects/{project.id}/repository",
        **guest_session,
    )
    assert res_guest_get.status_code == 403

    # 3. 管理员成功创建配置 (传 enabled=False 避免触发外部真实网络测试)
    create_payload = {
        "name": "Repo Admin Main",
        "remote_url": "git@github.com:example/test.git",
        "auth_type": "SSH_KEY",
        "credential_content": "MOCK_KEY_PRIVATE_ABCD",
        "main_branch": "main",
        "enabled": False,
    }

    res_create = await client.post(
        f"/api/v1/projects/{project.id}/repository",
        json=create_payload,
        **admin_session,
    )
    assert res_create.status_code == 200
    repo_data = res_create.json()
    assert repo_data["name"] == "Repo Admin Main"
    assert repo_data["has_credential"] is True
    # 验证元数据没有泄露明文凭证
    assert "credential_ref" not in repo_data
    assert "MOCK_KEY_PRIVATE_ABCD" not in str(repo_data)

    # 4. 获取验证：获取刚才的配置，has_credential 应为 True
    res_get = await client.get(
        f"/api/v1/projects/{project.id}/repository",
        **admin_session,
    )
    assert res_get.status_code == 200
    assert res_get.json()["has_credential"] is True
    assert res_get.json()["row_version"] == 1

    # 5. 乐观锁拦截更新：使用错误的 row_version 更新
    update_payload = {
        "name": "Repo Admin Main",
        "remote_url": "git@github.com:example/test.git",
        "auth_type": "SSH_KEY",
        "credential_content": None,  # 不修改凭证
        "main_branch": "main",
        "enabled": False,
        "row_version": 999,  # 错误的乐观锁版本
    }
    res_lock = await client.post(
        f"/api/v1/projects/{project.id}/repository",
        json=update_payload,
        **admin_session,
    )
    assert res_lock.status_code == 409

    # 6. 验证连接接口测试 (Mock 掉底层校验以防离线测试容器断网报错)
    verify_payload = {
        "remote_url": "git@github.com:example/test.git",
        "auth_type": "SSH_KEY",
        "credential_content": "MOCK_KEY_VAL",
        "main_branch": "main",
    }
    with patch("testweave.modules.repositories.service.RepositoryService.verify_connection") as mock_verify:
        res_verify = await client.post(
            f"/api/v1/projects/{project.id}/repository/verify",
            json=verify_payload,
            **admin_session,
        )
        assert res_verify.status_code == 200
        assert res_verify.json()["status"] == "success"
        assert mock_verify.call_count == 1

    # 7. 触发同步测试 (/sync)
    # 我们 mock 掉 sync_repository，在里面模拟写入一个 GitCommit 和 GitCommitFile 以及关联记录，以测试全流程
    from testweave.db.models import GitCommit, GitCommitFile, RequirementCommitLink, Requirement
    from testweave.modules.requirements.service import RequirementService

    # 插入一个需求
    req = RequirementService.create_requirement(
        session,
        project_id=project.id,
        requirement_no="REQ-4001",
        title="Sync Requirement Test",
        description=None,
        priority="MEDIUM",
        owner_id=project.owner_id,
        actor_id=project.owner_id,
        request_id="req-sync-mock",
    )
    session.commit()

    def mock_sync_impl(db: Session, repository_id: str, job_id: str) -> None:
        # 写入模拟的 commit 和文件
        repo_id = uuid.UUID(repository_id)
        c = GitCommit(
            repository_id=repo_id,
            sha="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
            author_name="Committer",
            author_email="c@tw.com",
            committer_name="Committer",
            committer_email="c@tw.com",
            authored_at=datetime.utcnow(),
            committed_at=datetime.utcnow(),
            message="[REQ-4001] Mock commit for sync testing",
            parent_shas_json=[],
            files_changed=1,
            additions=10,
            deletions=2,
            is_merge=False,
            is_reachable_from_main=True,
        )
        db.add(c)
        db.flush()

        cf = GitCommitFile(
            commit_id=c.id,
            new_path="src/main.py",
            change_type="ADD",
            is_binary=False,
            additions=10,
            deletions=2,
            patch_storage_key=None,
        )
        db.add(cf)
        db.flush()

        link = RequirementCommitLink(
            project_id=project.id,
            requirement_id=req.id,
            commit_id=c.id,
            matched_requirement_no="REQ-4001",
            match_revision=1,
            match_method="COMMIT_MESSAGE_EXACT_TOKEN",
            status="ACTIVE",
        )
        db.add(link)
        db.flush()

    with patch("testweave.modules.repositories.sync.RepositorySyncManager.sync_repository", side_effect=mock_sync_impl):
        res_sync = await client.post(
            f"/api/v1/projects/{project.id}/repository/sync",
            **admin_session,
        )
        assert res_sync.status_code == 200
        job_info = res_sync.json()
        assert job_info["status"] == "COMPLETED"  # 模拟执行直接 COMPLETED
        job_id = job_info["job_id"]

        # 轮询状态接口
        res_job = await client.get(
            f"/api/v1/projects/{project.id}/repository/sync/jobs/{job_id}",
            **admin_session,
        )
        assert res_job.status_code == 200
        assert res_job.json()["status"] == "COMPLETED"

    # 8. 查询关联的 Commit 列表接口
    res_commits = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/commits",
        **admin_session,
    )
    assert res_commits.status_code == 200
    commit_list = res_commits.json()
    assert len(commit_list) == 1
    assert commit_list[0]["sha"] == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
    commit_id = commit_list[0]["id"]

    # 9. 查询变动文件列表接口
    res_files = await client.get(
        f"/api/v1/projects/{project.id}/commits/{commit_id}/files",
        **admin_session,
    )
    assert res_files.status_code == 200
    file_list = res_files.json()
    assert len(file_list) == 1
    assert file_list[0]["new_path"] == "src/main.py"
    assert file_list[0]["change_type"] == "ADD"

    # 10. 重匹配测试 (/rematch)
    res_rematch = await client.post(
        f"/api/v1/projects/{project.id}/repository/rematch",
        **admin_session,
    )
    assert res_rematch.status_code == 200
    assert res_rematch.json()["links_rebuilt"] == 1

