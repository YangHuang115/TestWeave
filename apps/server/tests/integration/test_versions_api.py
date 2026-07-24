from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService

pytestmark = pytest.mark.integration


@pytest.fixture
async def integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """准备集成测试所需的用户和项目，并建立不同角色的客户端 session cookies"""
    # 创建三个测试用户
    admin_user = UserService.create_user(
        session,
        username="apiadmin",
        email="apiadmin@tw.com",
        display_name="API Admin",
        password="pwd",
    )
    member_user = UserService.create_user(
        session,
        username="apimember",
        email="apimember@tw.com",
        display_name="API Member",
        password="pwd",
    )
    guest_user = UserService.create_user(
        session,
        username="apiguest",
        email="apiguest@tw.com",
        display_name="API Guest",
        password="pwd",
    )
    session.commit()

    # 创建项目 (系统管理员创建并设 admin_user 为所有者/管理员)
    project = ProjectService.create_project(
        session,
        key="APIVPROJ",
        name="API Version Project",
        owner_id=admin_user.id,
        request_id="req-p",
    )
    session.commit()

    # 将 member_user 添加为项目 A 的测试成员 (test_member)
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
    # 1. 管理员登录
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "apiadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    # 2. 成员登录
    res_member = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "apimember", "password": "pwd"}
    )
    cookies_member = res_member.cookies
    csrf_member = cookies_member.get("xsrf_token")

    # 3. 访客登录
    res_guest = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "apiguest", "password": "pwd"}
    )
    cookies_guest = res_guest.cookies
    csrf_guest = cookies_guest.get("xsrf_token")

    return {
        "project": project,
        "admin_user": admin_user,
        "member_user": member_user,
        "guest_user": guest_user,
        "admin_session": {"cookies": cookies_admin, "headers": {"X-CSRF-Token": csrf_admin}},
        "member_session": {"cookies": cookies_member, "headers": {"X-CSRF-Token": csrf_member}},
        "guest_session": {"cookies": cookies_guest, "headers": {"X-CSRF-Token": csrf_guest}},
    }


@pytest.mark.anyio
async def test_version_api_lifecycle(
    client: AsyncClient, integration_context: dict[str, Any]
) -> None:
    project = integration_context["project"]
    admin_session = integration_context["admin_session"]
    member_session = integration_context["member_session"]
    guest_session = integration_context["guest_session"]
    admin_user = integration_context["admin_user"]

    # 1. 项目管理员成功创建版本 (POST)
    create_payload = {
        "key": "v1.0.0",
        "name": "Initial Release",
        "description": "API Integration Version test",
        "owner_id": str(admin_user.id),
        "planned_start_at": "2026-07-20T12:00:00Z",
        "planned_end_at": "2026-07-30T12:00:00Z",
    }

    res = await client.post(
        f"/api/v1/projects/{project.id}/versions",
        json=create_payload,
        **admin_session,
    )
    assert res.status_code == 201
    version_data = res.json()
    assert version_data["key"] == "v1.0.0"
    assert version_data["status"] == "PLANNING"
    assert version_data["rowVersion"] == 1
    version_id = version_data["id"]

    # 2. 项目隔离测试：非项目成员访问，返回 403
    res_guest = await client.get(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        **guest_session,
    )
    assert res_guest.status_code == 403
    assert res_guest.json()["code"] == "PROJECT_ACCESS_DENIED"

    # 3. 成员读取测试：测试成员（仅只读权限）能够成功获取详情和列表
    res_member_get = await client.get(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        **member_session,
    )
    assert res_member_get.status_code == 200
    assert res_member_get.json()["name"] == "Initial Release"

    res_member_list = await client.get(
        f"/api/v1/projects/{project.id}/versions",
        **member_session,
    )
    assert res_member_list.status_code == 200
    assert res_member_list.json()["total"] == 1

    # 4. 成员权限测试：测试成员尝试修改版本，返回 403
    res_member_patch = await client.patch(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        json={
            "name": "Unauthorized Update",
            "owner_id": str(admin_user.id),
            "status": "ACTIVE",
            "rowVersion": 1,
        },
        **member_session,
    )
    assert res_member_patch.status_code == 403
    assert res_member_patch.json()["code"] == "FORBIDDEN"

    # 5. 项目管理员乐观锁校验：用旧的 rowVersion 进行修改，返回 409
    res_admin_lock = await client.patch(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        json={
            "name": "Lock Update",
            "owner_id": str(admin_user.id),
            "status": "ACTIVE",
            "rowVersion": 0,  # 错误的 rowVersion
        },
        **admin_session,
    )
    assert res_admin_lock.status_code == 409
    assert res_admin_lock.json()["code"] == "OPTIMISTIC_LOCK_CONFLICT"

    # 6. 项目管理员成功更新版本状态流转 (PLANNING -> ACTIVE)
    res_admin_update = await client.patch(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        json={
            "name": "Initial Release Updated",
            "description": "Updated description",
            "owner_id": str(admin_user.id),
            "status": "ACTIVE",
            "rowVersion": 1,
        },
        **admin_session,
    )
    assert res_admin_update.status_code == 200
    updated_data = res_admin_update.json()
    assert updated_data["status"] == "ACTIVE"
    assert updated_data["rowVersion"] == 2

    # 7. 项目归档与恢复操作
    # 归档版本
    res_archive = await client.post(
        f"/api/v1/projects/{project.id}/versions/{version_id}/archive",
        **admin_session,
    )
    assert res_archive.status_code == 200
    assert res_archive.json()["status"] == "ARCHIVED"

    # 验证归档版本为只读
    res_patch_archived = await client.patch(
        f"/api/v1/projects/{project.id}/versions/{version_id}",
        json={
            "name": "Archived Update",
            "owner_id": str(admin_user.id),
            "status": "ARCHIVED",
            "rowVersion": 3,
        },
        **admin_session,
    )
    assert res_patch_archived.status_code == 403
    assert res_patch_archived.json()["code"] == "VERSION_ARCHIVED"

    # 恢复版本
    res_restore = await client.post(
        f"/api/v1/projects/{project.id}/versions/{version_id}/restore",
        **admin_session,
    )
    assert res_restore.status_code == 200
    assert res_restore.json()["status"] == "ACTIVE"  # 应该恢复为之前的 ACTIVE 状态
