from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService

pytestmark = pytest.mark.integration


@pytest.fixture
async def case_api_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """用例与模块 API 集成测试上下文"""
    admin_user = UserService.create_user(
        session,
        username="caseapiadmin",
        email="caseapiadmin@tw.com",
        display_name="Case API Admin",
        password="pwd",
    )
    session.commit()

    project = ProjectService.create_project(
        session,
        key="APICASEPROJ",
        name="API Case Project",
        owner_id=admin_user.id,
        request_id="req-p-case",
    )
    session.commit()

    # 登录 session 获得 Cookie 鉴权与 CSRF Token
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "caseapiadmin", "password": "pwd"},
    )
    assert login_res.status_code == 200
    cookies = dict(login_res.cookies)
    csrf_token = cookies.get("xsrf_token")
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}

    return {
        "admin_user": admin_user,
        "project": project,
        "headers": headers,
    }


@pytest.mark.anyio
async def test_case_modules_api_lifecycle(
    client: AsyncClient, case_api_context: dict[str, Any]
) -> None:
    project = case_api_context["project"]
    project_id = str(project.id)
    headers = case_api_context["headers"]

    # 1. 创建根模块 1 与根模块 2
    res_m1 = await client.post(
        f"/api/v1/projects/{project_id}/case-modules",
        json={"name": "核心功能", "description": "核心功能模块", "sortOrder": 1},
        headers=headers,
    )
    assert res_m1.status_code == 200
    m1_data = res_m1.json()
    assert m1_data["name"] == "核心功能"
    m1_id = m1_data["id"]

    res_m2 = await client.post(
        f"/api/v1/projects/{project_id}/case-modules",
        json={"name": "辅助工具", "sortOrder": 2},
        headers=headers,
    )
    assert res_m2.status_code == 200
    m2_id = res_m2.json()["id"]

    # 2. 在根模块 1 下创建子模块 1-1
    res_sub = await client.post(
        f"/api/v1/projects/{project_id}/case-modules",
        json={"name": "用户中心", "parentId": m1_id, "sortOrder": 1},
        headers=headers,
    )
    assert res_sub.status_code == 200
    sub_id = res_sub.json()["id"]

    # 3. 获取模块树
    res_tree = await client.get(f"/api/v1/projects/{project_id}/case-modules/tree")
    assert res_tree.status_code == 200
    tree_data = res_tree.json()
    assert len(tree_data) == 2
    assert tree_data[0]["name"] == "核心功能"
    assert len(tree_data[0]["children"]) == 1
    assert tree_data[0]["children"][0]["name"] == "用户中心"

    # 4. 移动子模块 1-1 到根模块 2 之下
    res_move = await client.put(
        f"/api/v1/projects/{project_id}/case-modules/{sub_id}/move",
        json={"targetParentId": m2_id},
        headers=headers,
    )
    assert res_move.status_code == 200
    assert res_move.json()["parentId"] == m2_id

    # 5. 归档移空后的根模块 1
    res_arch = await client.post(
        f"/api/v1/projects/{project_id}/case-modules/{m1_id}/archive",
        headers=headers,
    )
    assert res_arch.status_code == 200
    assert res_arch.json()["archivedAt"] is not None


@pytest.mark.anyio
async def test_test_cases_api_lifecycle(
    client: AsyncClient, case_api_context: dict[str, Any]
) -> None:
    project = case_api_context["project"]
    project_id = str(project.id)
    headers = case_api_context["headers"]

    # 先创建一个模块
    res_m = await client.post(
        f"/api/v1/projects/{project_id}/case-modules",
        json={"name": "API测试模块"},
        headers=headers,
    )
    assert res_m.status_code == 200
    mod_id = res_m.json()["id"]

    # 1. 创建测试用例
    case_payload = {
        "title": "API 登录测试用例",
        "precondition": "系统服务正常运行",
        "priority": "HIGH",
        "caseType": "FUNCTIONAL",
        "tagsJson": ["API", "Login"],
        "testDataNote": "Test Account",
        "note": "无",
        "steps": [
            {"action": "发送 POST /login", "expectedResult": "返回 200 Token"},
        ],
        "moduleIds": [mod_id],
    }
    res_create = await client.post(
        f"/api/v1/projects/{project_id}/test-cases",
        json=case_payload,
        headers=headers,
    )
    assert res_create.status_code == 200
    case_data = res_create.json()
    assert case_data["caseNo"] == "TC-000001"
    assert case_data["rowVersion"] == 1
    case_id = case_data["id"]

    # 2. 查询用例列表 (带 moduleId 过滤)
    res_list = await client.get(f"/api/v1/projects/{project_id}/test-cases?moduleId={mod_id}")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == case_id

    # 3. 查询用例详情
    res_detail = await client.get(f"/api/v1/projects/{project_id}/test-cases/{case_id}")
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert len(detail_data["steps"]) == 1
    assert detail_data["steps"][0]["action"] == "发送 POST /login"

    # 4. 开启编辑会话
    res_sess = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/edit-sessions",
        headers=headers,
    )
    assert res_sess.status_code == 200
    sess_data = res_sess.json()
    assert sess_data["status"] == "OPEN"
    sess_id = sess_data["id"]

    # 5. 暂存草稿
    res_draft = await client.put(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/edit-sessions/{sess_id}/draft",
        json={"dirtyFields": {"title": "API 登录测试用例(已更新)"}},
        headers=headers,
    )
    assert res_draft.status_code == 200
    assert res_draft.json()["dirtyFields"]["title"] == "API 登录测试用例(已更新)"

    # 6. 提交发布会话
    res_fin = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/edit-sessions/{sess_id}/finalize",
        json={"changeSummary": {"note": "首次修改"}},
        headers=headers,
    )
    assert res_fin.status_code == 200
    rev_data = res_fin.json()
    assert rev_data["revisionNo"] == 2

    # 7. 查询历史版本列表
    res_revs = await client.get(f"/api/v1/projects/{project_id}/test-cases/{case_id}/revisions")
    assert res_revs.status_code == 200
    revs_data = res_revs.json()
    assert len(revs_data) == 2
    assert revs_data[0]["revisionNo"] == 2
