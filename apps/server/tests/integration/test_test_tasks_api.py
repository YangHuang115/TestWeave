from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService

pytestmark = pytest.mark.integration


@pytest.fixture
async def task_integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """准备测试任务集成测试上下文"""
    # 1. 创建三个测试用户
    admin_user = UserService.create_user(
        session,
        username="taskapiadmin",
        email="taskapiadmin@tw.com",
        display_name="Task API Admin",
        password="pwd",
    )
    member_user = UserService.create_user(
        session,
        username="taskapimember",
        email="taskapimember@tw.com",
        display_name="Task API Member",
        password="pwd",
    )
    UserService.create_user(
        session,
        username="taskapiguest",
        email="taskapiguest@tw.com",
        display_name="Task API Guest",
        password="pwd",
    )
    session.commit()

    # 2. 创建项目
    project = ProjectService.create_project(
        session,
        key="APITASKPROJ",
        name="API Task Project",
        owner_id=admin_user.id,
        request_id="req-p",
    )
    session.commit()

    # 3. 添加 member_user 为测试成员
    ProjectService.add_member(
        session,
        project_id=project.id,
        user_id=member_user.id,
        role_id="test_member",
        actor_id=admin_user.id,
        request_id="req-m",
    )
    session.commit()

    # 4. 创建版本
    now_time = datetime.now(UTC)
    version = VersionService.create_version(
        session,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0 Release",
        owner_id=admin_user.id,
        planned_start_at=now_time - timedelta(days=1),
        planned_end_at=now_time + timedelta(days=10),
        actor_id=admin_user.id,
        request_id="req-v",
    )
    session.commit()

    # 5. 创建需求并关联版本
    req = RequirementService.create_requirement(
        session,
        project_id=project.id,
        requirement_no="REQ-101",
        title="短信功能测试",
        description="",
        priority="HIGH",
        owner_id=admin_user.id,
        actor_id=admin_user.id,
        request_id="req-req",
    )
    RequirementService.associate_to_version(
        session,
        project_id=project.id,
        requirement_id=req.id,
        version_id=version.id,
        actor_id=admin_user.id,
        request_id="req-assoc",
    )
    session.commit()

    # 6. 登录并获取 cookies 与 csrf 令牌
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "taskapiadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    res_member = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "taskapimember", "password": "pwd"}
    )
    cookies_member = res_member.cookies
    csrf_member = cookies_member.get("xsrf_token")

    res_guest = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "taskapiguest", "password": "pwd"}
    )
    cookies_guest = res_guest.cookies
    csrf_guest = cookies_guest.get("xsrf_token")

    return {
        "project": project,
        "version": version,
        "requirement": req,
        "admin_user": admin_user,
        "member_user": member_user,
        "admin_session": {"cookies": cookies_admin, "headers": {"X-CSRF-Token": csrf_admin}},
        "member_session": {"cookies": cookies_member, "headers": {"X-CSRF-Token": csrf_member}},
        "guest_session": {"cookies": cookies_guest, "headers": {"X-CSRF-Token": csrf_guest}},
    }


@pytest.mark.anyio
async def test_task_api_lifecycle(
    client: AsyncClient, task_integration_context: dict[str, Any]
) -> None:
    project = task_integration_context["project"]
    version = task_integration_context["version"]
    requirement = task_integration_context["requirement"]
    task_integration_context["admin_user"]
    member_user = task_integration_context["member_user"]
    task_integration_context["admin_session"]
    member_session = task_integration_context["member_session"]
    guest_session = task_integration_context["guest_session"]

    # 1. 普通测试成员成功创建设计任务 (POST)
    now_time = datetime.now(UTC)
    planned_end = now_time + timedelta(days=5)
    create_payload = {
        "title": "短信渠道集成设计",
        "versionId": str(version.id),
        "taskType": "CASE_DESIGN",
        "ownerId": str(member_user.id),
        "plannedStartAt": now_time.isoformat(),
        "plannedEndAt": planned_end.isoformat(),
        "priority": "HIGH",
        "description": "进行系统化设计",
        "testGoal": "覆盖高并发",
        "excludedScope": "暂无",
        "tagsJson": ["SMS", "Design"],
        "requirementId": str(requirement.id),
    }

    res = await client.post(
        f"/api/v1/projects/{project.id}/test-tasks", json=create_payload, **member_session
    )
    assert res.status_code == 201
    task_data = res.json()
    assert task_data["title"] == "短信渠道集成设计"
    assert task_data["taskNo"] == "TASK-000001"
    assert task_data["status"] == "DRAFT"
    assert task_data["rowVersion"] == 1
    task_id = task_data["id"]

    # 2. 非项目成员访问该任务详情，被拒绝 (GET)
    res = await client.get(f"/api/v1/projects/{project.id}/test-tasks/{task_id}", **guest_session)
    assert res.status_code == 403

    # 3. 关联需求且获得重复提醒校验 (PUT)
    assoc_res = await client.put(
        f"/api/v1/projects/{project.id}/test-tasks/{task_id}/requirements",
        json={"requirementId": str(requirement.id)},
        **member_session,
    )
    assert assoc_res.status_code == 200
    assoc_data = assoc_res.json()
    assert len(assoc_data["warnings"]) == 0
    assert assoc_data["task"]["rowVersion"] == 2

    # 4. 执行状态流转 READY -> IN_PROGRESS (POST)
    # 首先流转至 READY
    trans_ready_payload = {"targetStatus": "READY", "rowVersion": assoc_data["task"]["rowVersion"]}
    res = await client.post(
        f"/api/v1/projects/{project.id}/test-tasks/{task_id}/transitions",
        json=trans_ready_payload,
        **member_session,
    )
    assert res.status_code == 200
    task_data = res.json()
    assert task_data["status"] == "READY"

    # 流转至 IN_PROGRESS
    trans_progress_payload = {"targetStatus": "IN_PROGRESS", "rowVersion": task_data["rowVersion"]}
    res = await client.post(
        f"/api/v1/projects/{project.id}/test-tasks/{task_id}/transitions",
        json=trans_progress_payload,
        **member_session,
    )
    assert res.status_code == 200
    task_data = res.json()
    assert task_data["status"] == "IN_PROGRESS"

    # 5. 乐观锁冲突更新 (PATCH)
    # 使用过期的 rowVersion 进行 patch
    update_payload = {
        "title": "修改标题",
        "priority": "HIGH",
        "ownerId": str(member_user.id),
        "plannedStartAt": task_data["plannedStartAt"],
        "plannedEndAt": task_data["plannedEndAt"],
        "rowVersion": task_data["rowVersion"] - 1,  # 过期版本
    }
    res = await client.patch(
        f"/api/v1/projects/{project.id}/test-tasks/{task_id}", json=update_payload, **member_session
    )
    assert res.status_code == 409

    # 6. 工作台摘要 API 校验 (GET)
    res = await client.get(f"/api/v1/projects/{project.id}/test-tasks/my-summary", **member_session)
    assert res.status_code == 200
    summary_data = res.json()
    print("DEBUG_SUMMARY_DATA:", summary_data)
    assert summary_data["myInProgressCount"] == 1

    # 7. 测试查询关联需求 (GET)
    res_reqs = await client.get(
        f"/api/v1/projects/{project.id}/test-tasks/{task_id}/requirements", **member_session
    )
    assert res_reqs.status_code == 200
    reqs_data = res_reqs.json()
    assert len(reqs_data) == 1
