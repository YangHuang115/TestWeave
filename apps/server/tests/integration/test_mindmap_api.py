from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.test_tasks.service import TestTaskService

pytestmark = pytest.mark.integration


@pytest.fixture
async def mindmap_api_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """脑图 API 测试上下文，建立完备的 User, Project, Version, Requirement 和 TestTask"""
    admin_user = UserService.create_user(
        session,
        username="mmapadmin",
        email="mmapadmin@tw.com",
        display_name="Mindmap Admin",
        password="pwd",
    )
    session.commit()

    project = ProjectService.create_project(
        session,
        key="MMPROJ",
        name="Mindmap Project",
        owner_id=admin_user.id,
        request_id="req-p-mm",
    )
    session.commit()

    version = VersionService.create_version(
        session,
        project_id=project.id,
        key="v1.0",
        name="Version 1",
        owner_id=admin_user.id,
        planned_start_at=datetime.now(UTC),
        planned_end_at=datetime.now(UTC) + timedelta(days=10),
        actor_id=admin_user.id,
        request_id="req-v-mm",
    )
    session.commit()

    req = RequirementService.create_requirement(
        session,
        project_id=project.id,
        requirement_no="REQ-9999",
        title="测试脑图需求",
        description="需求说明",
        priority="HIGH",
        owner_id=admin_user.id,
        actor_id=admin_user.id,
        request_id="req-r-mm",
    )
    RequirementService.associate_to_version(
        session,
        project_id=str(project.id),
        requirement_id=str(req.id),
        version_id=str(version.id),
        actor_id=str(admin_user.id),
        request_id="req-r-mm-assoc",
    )
    session.commit()

    now_time = datetime.now(UTC)
    task = TestTaskService.create_task(
        session,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="支付用例设计",
        description="设计任务",
        priority="HIGH",
        owner_id=admin_user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal="覆盖支付全部成功与异常拦截路径",
        excluded_scope="不包括退款流程",
        tags_json=["支付", "用例设计"],
        actor_id=admin_user.id,
        request_id="req-task-mm1",
        requirement_id=req.id,
    )
    session.commit()

    # 登录 session 获得 Cookie 鉴权与 CSRF Token
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "mmapadmin", "password": "pwd"},
    )
    assert login_res.status_code == 200
    cookies = dict(login_res.cookies)
    csrf_token = cookies.get("xsrf_token")
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}

    return {
        "admin_user": admin_user,
        "project": project,
        "task": task,
        "headers": headers,
    }


@pytest.mark.anyio
async def test_mindmap_api_lifecycle(
    client: AsyncClient, mindmap_api_context: dict[str, Any]
) -> None:
    project_id = str(mindmap_api_context["project"].id)
    task_id = str(mindmap_api_context["task"].id)
    headers = mindmap_api_context["headers"]

    # 1. GET 获取初始/自动创建的空脑图
    res_get = await client.get(
        f"/api/v1/projects/{project_id}/test-tasks/{task_id}/mindmap",
        headers=headers,
    )
    assert res_get.status_code == 200
    mm_data = res_get.json()
    assert mm_data["title"] == "新测试点脑图"
    assert mm_data["data"]["nodeData"]["topic"] == "测试用例脑图"

    # 2. PUT 修改保存脑图
    new_data = {
        "nodeData": {
            "id": "root",
            "topic": "登录功能测试点",
            "children": [
                {
                    "id": "node-1",
                    "topic": "正常流程",
                    "children": [
                        {
                            "id": "node-2",
                            "topic": "账号密码登录",
                            "children": [
                                {
                                    "id": "node-3",
                                    "topic": "提示登录成功"
                                }
                            ]
                        }
                    ]
                },
                {
                    "id": "node-4",
                    "topic": "安全测试",
                    "children": [
                        {
                            "id": "node-5",
                            "topic": "密码暴力破解防护",
                            "children": [
                                {
                                    "id": "node-6",
                                    "topic": "连续错误5次锁定账号"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
    
    res_put = await client.put(
        f"/api/v1/projects/{project_id}/test-tasks/{task_id}/mindmap",
        json={"title": "登录深度测试脑图", "data": new_data},
        headers=headers,
    )
    assert res_put.status_code == 200
    mm_updated = res_put.json()
    assert mm_updated["title"] == "登录深度测试脑图"
    assert mm_updated["data"]["nodeData"]["children"][0]["topic"] == "正常流程"

    # 3. POST 一键同步到测试用例库
    res_sync = await client.post(
        f"/api/v1/projects/{project_id}/test-tasks/{task_id}/mindmap/sync",
        headers=headers,
    )
    assert res_sync.status_code == 200
    sync_res = res_sync.json()
    assert sync_res["status"] == "SUCCESS"
    assert sync_res["syncedCount"] == 2  # 一共 2 个叶子节点：提示登录成功、连续错误5次锁定账号

    # 4. 再次 GET 用例列表验证同步结果
    res_cases = await client.get(
        f"/api/v1/projects/{project_id}/test-cases",
        headers=headers,
    )
    assert res_cases.status_code == 200
    cases_list = res_cases.json()
    assert len(cases_list) == 2

    # 验证标题拼接和标签
    case_titles = [c["title"] for c in cases_list]
    assert "正常流程-账号密码登录-提示登录成功" in case_titles
    assert "安全测试-密码暴力破解防护-连续错误5次锁定账号" in case_titles
    assert cases_list[0]["tagsJson"] == ["mindmap-sync"]
