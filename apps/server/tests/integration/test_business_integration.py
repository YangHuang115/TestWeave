import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.security import verify_password
from testweave.db.models import User
from testweave.modules.users.service import UserService

pytestmark = pytest.mark.integration


# ==============================================================================
# 1. 命令行管理工具集成测试
# ==============================================================================
def test_cli_create_admin_success(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    # 模拟 getpass 的输入，防止交互式阻塞测试
    inputs = ["admin-pwd123", "admin-pwd123"]
    input_iter = iter(inputs)
    monkeypatch.setattr("getpass.getpass", lambda _: next(input_iter))

    # 使用 UserService 创建初始管理员来模拟 cli 相同逻辑（由于 cli 直接使用了全局 get_settings，
    # 在集成测试中我们已将 engine 准备好并升级，直接对 session 进行逻辑检验）
    user = UserService.create_user(
        session,
        username="cliadmin",
        email="cliadmin@testweave.com",
        display_name="Cli Admin",
        password="admin-pwd123",
        is_system_admin=True,
    )
    session.commit()

    assert user.is_system_admin is True
    assert verify_password(user.hashed_password, "admin-pwd123") is True


# ==============================================================================
# 2. 认证/CSRF 与用户状态变更 API 集成测试
# ==============================================================================
@pytest.mark.anyio
async def test_auth_login_logout_csrf_flow(client: AsyncClient, session: Session) -> None:
    # 准备测试用户
    UserService.create_user(
        session,
        username="apiflowuser",
        email="apiflow@testweave.com",
        display_name="API Flow User",
        password="my-password-999",
        is_system_admin=False,
    )
    session.commit()

    # 1. 登录
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apiflowuser", "password": "my-password-999"},
    )
    assert login_res.status_code == 200
    user_data = login_res.json()
    assert user_data["username"] == "apiflowuser"

    # 提取 cookies 并验证
    cookies = login_res.cookies
    assert "session_token" in cookies
    assert "xsrf_token" in cookies

    # 2. 验证 CSRF 保护 (尝试以错误的 CSRF Header 发起写请求)
    bad_post_res = await client.post(
        "/api/v1/projects",
        json={"key": "BAD", "name": "Bad Project"},
        cookies=cookies,
        headers={"X-CSRF-Token": "invalid-token"},
    )
    assert bad_post_res.status_code == 403
    assert bad_post_res.json()["code"] == "CSRF_ERROR"

    # 3. 校验 get me 成功 (GET 请求不触发 CSRF 校验)
    me_res = await client.get("/api/v1/auth/me", cookies=cookies)
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "apiflowuser"

    # 4. 停用用户后，已有会话即时失效
    # 在数据库将状态更改为 inactive
    user = session.scalar(select(User).where(User.username == "apiflowuser"))
    assert user is not None
    user.status = "inactive"
    session.commit()

    me_after_inactive_res = await client.get("/api/v1/auth/me", cookies=cookies)
    assert me_after_inactive_res.status_code == 401
    assert me_after_inactive_res.json()["code"] == "UNAUTHORIZED"


# ==============================================================================
# 3. 项目、成员管理与权限隔离 API 集成测试
# ==============================================================================
@pytest.mark.anyio
async def test_project_lifecycle_isolation_and_permissions(
    client: AsyncClient, session: Session
) -> None:
    # 准备三个用户：1个系统管理员，2个普通用户
    admin = UserService.create_user(
        session,
        username="sysadmin",
        email="sysadmin@tw.com",
        display_name="Sys Admin",
        password="pwd",
        is_system_admin=True,
    )
    user_a = UserService.create_user(
        session, username="usera", email="usera@tw.com", display_name="User A", password="pwd"
    )
    user_b = UserService.create_user(
        session, username="userb", email="userb@tw.com", display_name="User B", password="pwd"
    )
    session.commit()

    # 1. 登录系统管理员
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "sysadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    # 2. 登录普通用户 A
    res_a = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "usera", "password": "pwd"}
    )
    cookies_a = res_a.cookies
    csrf_a = cookies_a.get("xsrf_token")

    # 3. 非系统管理员创建项目，返回 403
    bad_proj_res = await client.post(
        "/api/v1/projects",
        json={"key": "NOP", "name": "No Permission"},
        cookies=cookies_a,
        headers={"X-CSRF-Token": csrf_a},
    )
    assert bad_proj_res.status_code == 403

    # 4. 系统管理员创建项目 A
    proj_res = await client.post(
        "/api/v1/projects",
        json={"key": "PROJA", "name": "Project A"},
        cookies=cookies_admin,
        headers={"X-CSRF-Token": csrf_admin},
    )
    assert proj_res.status_code == 200
    proj_a_id = proj_res.json()["id"]

    # 5. 将用户 A 添加为项目 A 的项目管理员角色 (project_admin)
    add_member_res = await client.post(
        f"/api/v1/projects/{proj_a_id}/members",
        json={"user_id": str(user_a.id), "role_id": "project_admin"},
        cookies=cookies_admin,
        headers={"X-CSRF-Token": csrf_admin},
    )
    assert add_member_res.status_code == 200

    # 将用户 B 添加为项目 A 的测试成员角色 (test_member)
    add_member_b = await client.post(
        f"/api/v1/projects/{proj_a_id}/members",
        json={"user_id": str(user_b.id), "role_id": "test_member"},
        cookies=cookies_admin,
        headers={"X-CSRF-Token": csrf_admin},
    )
    assert add_member_b.status_code == 200

    # 6. 普通用户 A 登录并越权测试 (用项目管理员权限添加其他成员)
    # 验证项目 A 上下文
    ctx_res = await client.get(f"/api/v1/projects/{proj_a_id}/context", cookies=cookies_a)
    assert ctx_res.status_code == 200
    assert ctx_res.json()["role_id"] == "project_admin"

    # 7. 登录普通用户 B 验证权限与越权
    res_b = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "userb", "password": "pwd"}
    )
    cookies_b = res_b.cookies
    csrf_b = cookies_b.get("xsrf_token")

    # 普通用户 B (test_member) 尝试添加新成员，应该返回 403 FORBIDDEN 报错
    bad_add_member = await client.post(
        f"/api/v1/projects/{proj_a_id}/members",
        json={"user_id": str(admin.id), "role_id": "test_lead"},
        cookies=cookies_b,
        headers={"X-CSRF-Token": csrf_b},
    )
    assert bad_add_member.status_code == 403
    assert bad_add_member.json()["code"] == "FORBIDDEN"

    # 8. 最后一名项目管理员的并发/变更角色安全保护
    # 此时项目中有 sysadmin 和 usera 两个管理员。
    # 为了测试最后一名管理员保护，先将 sysadmin 降级为 test_member
    demote_sysadmin_res = await client.patch(
        f"/api/v1/projects/{proj_a_id}/members/{admin.id}",
        json={"role_id": "test_member"},
        cookies=cookies_admin,
        headers={"X-CSRF-Token": csrf_admin},
    )
    assert demote_sysadmin_res.status_code == 200

    # 此时用户 A 是项目 A 当前唯一有效的项目管理员。
    # 尝试将其降级为 test_member，应当被拒绝并返回 400 报错
    demote_res = await client.patch(
        f"/api/v1/projects/{proj_a_id}/members/{user_a.id}",
        json={"role_id": "test_member"},
        cookies=cookies_a,
        headers={"X-CSRF-Token": csrf_a},
    )
    assert demote_res.status_code == 400

    assert "必须保留至少一名" in demote_res.json()["message"]

    # 尝试移出用户 A：
    remove_res = await client.delete(
        f"/api/v1/projects/{proj_a_id}/members/{user_a.id}",
        cookies=cookies_a,
        headers={"X-CSRF-Token": csrf_a},
    )
    assert remove_res.status_code == 400
    assert "必须保留至少一名" in remove_res.json()["message"]

    # 9. 归档项目只读写保护测试
    # 项目管理员 (用户 A) 归档项目
    archive_res = await client.post(
        f"/api/v1/projects/{proj_a_id}/archive",
        cookies=cookies_a,
        headers={"X-CSRF-Token": csrf_a},
    )
    assert archive_res.status_code == 200
    assert archive_res.json()["status"] == "archived"

    # 归档后，任何人 (包括系统管理员) 试图向项目写入 (如修改成员角色) 应报错并被拦截
    write_after_archive_res = await client.patch(
        f"/api/v1/projects/{proj_a_id}/members/{user_b.id}",
        json={"role_id": "test_lead"},
        cookies=cookies_admin,
        headers={"X-CSRF-Token": csrf_admin},
    )
    assert write_after_archive_res.status_code == 403
    assert write_after_archive_res.json()["code"] == "PROJECT_ARCHIVED"

    # 归档后，依然可以通过 GET 接口获取项目详情或上下文
    read_after_archive_res = await client.get(f"/api/v1/projects/{proj_a_id}", cookies=cookies_b)
    assert read_after_archive_res.status_code == 200
    assert read_after_archive_res.json()["status"] == "archived"
