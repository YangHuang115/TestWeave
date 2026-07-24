import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.db.models import CodeRepository, GitCommit, RequirementCommitLink
from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService

pytestmark = pytest.mark.integration


@pytest.fixture
async def req_integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """准备集成测试所需的用户、项目和版本，并建立不同角色的客户端 session cookies"""
    # 建立测试用户
    admin_user = UserService.create_user(
        session,
        username="reqapiadmin",
        email="ra@tw.com",
        display_name="Req API Admin",
        password="pwd",
    )
    member_user = UserService.create_user(
        session,
        username="reqapimember",
        email="rm@tw.com",
        display_name="Req API Member",
        password="pwd",
    )
    guest_user = UserService.create_user(
        session,
        username="reqapiguest",
        email="rg@tw.com",
        display_name="Req API Guest",
        password="pwd",
    )
    session.commit()

    # 建立项目与版本
    project = ProjectService.create_project(
        session, key="REQAPIP", name="Req API Project", owner_id=admin_user.id, request_id="req-p"
    )
    session.commit()

    version = VersionService.create_version(
        session,
        project_id=project.id,
        key="v1.0",
        name="API Version 1.0",
        owner_id=admin_user.id,
        actor_id=admin_user.id,
        request_id="req-v",
    )
    session.commit()

    # 将 member_user 添加为项目测试成员
    ProjectService.add_member(
        session,
        project_id=project.id,
        user_id=member_user.id,
        role_id="test_member",
        actor_id=admin_user.id,
        request_id="req-m",
    )
    session.commit()

    # 登录并获取 cookies 与 csrf 令牌
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "reqapiadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    res_member = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "reqapimember", "password": "pwd"}
    )
    cookies_member = res_member.cookies
    csrf_member = cookies_member.get("xsrf_token")

    res_guest = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "reqapiguest", "password": "pwd"}
    )
    cookies_guest = res_guest.cookies
    csrf_guest = cookies_guest.get("xsrf_token")

    return {
        "project": project,
        "version": version,
        "admin_user": admin_user,
        "member_user": member_user,
        "guest_user": guest_user,
        "admin_session": {"cookies": cookies_admin, "headers": {"X-CSRF-Token": csrf_admin}},
        "member_session": {"cookies": cookies_member, "headers": {"X-CSRF-Token": csrf_member}},
        "guest_session": {"cookies": cookies_guest, "headers": {"X-CSRF-Token": csrf_guest}},
    }


@pytest.mark.anyio
async def test_requirement_api_lifecycle(
    client: AsyncClient, session: Session, req_integration_context: dict[str, Any]
) -> None:
    project = req_integration_context["project"]
    version = req_integration_context["version"]
    admin_session = req_integration_context["admin_session"]
    member_session = req_integration_context["member_session"]
    guest_session = req_integration_context["guest_session"]
    admin_user = req_integration_context["admin_user"]

    # 1. 项目管理员成功创建需求并绑定到版本 (POST)
    create_payload = {
        "title": "API test requirement",
        "description": "Integration test for requirement API",
        "priority": "HIGH",
        "owner_id": str(admin_user.id),
    }

    res_create = await client.post(
        f"/api/v1/projects/{project.id}/versions/{version.id}/requirements",
        json=create_payload,
        **admin_session,
    )
    assert res_create.status_code == 201
    req_data = res_create.json()
    assert req_data["requirement_no"] == "REQ-10001"
    assert req_data["status"] == "DRAFT"
    assert req_data["rowVersion"] == 1
    req_id = req_data["id"]

    # 2. 项目隔离测试：非项目成员访问该版本下的需求列表，返回 403
    res_guest_list = await client.get(
        f"/api/v1/projects/{project.id}/versions/{version.id}/requirements",
        **guest_session,
    )
    assert res_guest_list.status_code == 403

    # 3. 成员读取测试：测试成员能获取版本下需求列表和需求详情
    res_member_list = await client.get(
        f"/api/v1/projects/{project.id}/versions/{version.id}/requirements",
        **member_session,
    )
    assert res_member_list.status_code == 200
    assert len(res_member_list.json()) == 1
    assert res_member_list.json()[0]["requirement_no"] == "REQ-10001"

    res_member_detail = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req_id}",
        **member_session,
    )
    assert res_member_detail.status_code == 200
    assert res_member_detail.json()["title"] == "API test requirement"

    # 4. 乐观锁更新冲突测试：使用错误的 rowVersion 更新，返回 409
    update_payload = {
        "requirement_no": "REQ-10001",
        "title": "API test requirement updated",
        "description": "Updated description",
        "priority": "HIGH",
        "owner_id": str(admin_user.id),
        "status": "READY",
        "rowVersion": 0,  # 错误的 rowVersion
        "force_change_no": False,
    }
    res_admin_lock = await client.patch(
        f"/api/v1/projects/{project.id}/requirements/{req_id}",
        json=update_payload,
        **admin_session,
    )
    assert res_admin_lock.status_code == 409

    # 5. 代码提交关联冲突测试
    # 模拟代码提交关联 (顺延外键)
    repo = CodeRepository(
        project_id=project.id,
        name="test-repo",
        remote_url="https://github.com/test/repo.git",
    )
    session.add(repo)
    session.flush()

    commit = GitCommit(
        repository_id=repo.id,
        sha="abcdef1234567890abcdef1234567890abcdef12",
        author_name="author",
        author_email="author@tw.com",
        committer_name="committer",
        committer_email="committer@tw.com",
        authored_at=datetime.now(UTC),
        committed_at=datetime.now(UTC),
        message="feat: REQ-10001 test commit",
    )
    session.add(commit)
    session.flush()

    commit_link = RequirementCommitLink(
        project_id=project.id,
        requirement_id=uuid.UUID(req_id),
        commit_id=commit.id,
        matched_requirement_no="REQ-10001",
    )
    session.add(commit_link)
    session.commit()

    # 5.1. 尝试更新单号为 REQ-2002 且 force_change_no 为 False，应该返回 400 REQUIREMENT_HAS_COMMITS
    update_payload["requirement_no"] = "REQ-2002"
    update_payload["rowVersion"] = 1
    res_admin_commits = await client.patch(
        f"/api/v1/projects/{project.id}/requirements/{req_id}",
        json=update_payload,
        **admin_session,
    )
    assert res_admin_commits.status_code == 400
    assert res_admin_commits.json()["code"] == "REQUIREMENT_HAS_COMMITS"

    # 5.2. 传入 force_change_no = True，应该成功修改，且旧关联被删除
    update_payload["force_change_no"] = True
    res_admin_force = await client.patch(
        f"/api/v1/projects/{project.id}/requirements/{req_id}",
        json=update_payload,
        **admin_session,
    )
    assert res_admin_force.status_code == 200
    assert res_admin_force.json()["requirement_no"] == "REQ-2002"
    assert res_admin_force.json()["rowVersion"] == 2

    # 6. 解除需求与版本的关联 (DELETE)
    res_dissociate = await client.delete(
        f"/api/v1/projects/{project.id}/versions/{version.id}/requirements/{req_id}",
        **admin_session,
    )
    assert res_dissociate.status_code == 204

    # 验证列表为空
    res_list_after = await client.get(
        f"/api/v1/projects/{project.id}/versions/{version.id}/requirements",
        **admin_session,
    )
    assert len(res_list_after.json()) == 0
