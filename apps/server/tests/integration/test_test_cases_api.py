from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.db.models import TestCase as TestCaseModel
from testweave.db.models import TestCaseEditSession as TestCaseEditSessionModel
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
    other_project = ProjectService.create_project(
        session,
        key="APICASEOTHER",
        name="Other API Case Project",
        owner_id=admin_user.id,
        request_id="req-p-case-other",
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
        "other_project": other_project,
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

    # 8. 同项目放弃新编辑会话
    res_sess_abandon = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/edit-sessions",
        headers=headers,
    )
    assert res_sess_abandon.status_code == 200
    abandon_session_id = res_sess_abandon.json()["id"]

    res_abandon = await client.post(
        f"/api/v1/projects/{project_id}/test-cases/{case_id}/edit-sessions/{abandon_session_id}/abandon",
        headers=headers,
    )
    assert res_abandon.status_code == 200
    assert res_abandon.json()["status"] == "ABANDONED"


@pytest.mark.anyio
async def test_case_module_endpoints_reject_cross_project_ids(
    client: AsyncClient,
    case_api_context: dict[str, Any],
) -> None:
    project_id = str(case_api_context["project"].id)
    other_project_id = str(case_api_context["other_project"].id)
    headers = case_api_context["headers"]

    async def create_module(target_project_id: str, name: str) -> str:
        response = await client.post(
            f"/api/v1/projects/{target_project_id}/case-modules",
            json={"name": name},
            headers=headers,
        )
        assert response.status_code == 200
        return response.json()["id"]

    local_module_id = await create_module(project_id, "Local module")
    foreign_module_id = await create_module(other_project_id, "Foreign module")
    foreign_parent_id = await create_module(other_project_id, "Foreign parent")
    foreign_archive_id = await create_module(other_project_id, "Foreign archive")

    responses = [
        await client.post(
            f"/api/v1/projects/{project_id}/case-modules",
            json={"name": "Cross-project child", "parentId": foreign_parent_id},
            headers=headers,
        ),
        await client.put(
            f"/api/v1/projects/{project_id}/case-modules/{foreign_module_id}",
            json={"name": "Leaked update", "sortOrder": 0},
            headers=headers,
        ),
        await client.put(
            f"/api/v1/projects/{project_id}/case-modules/{foreign_module_id}/move",
            json={"targetParentId": None},
            headers=headers,
        ),
        await client.put(
            f"/api/v1/projects/{project_id}/case-modules/{local_module_id}/move",
            json={"targetParentId": foreign_parent_id},
            headers=headers,
        ),
        await client.post(
            f"/api/v1/projects/{project_id}/case-modules/{foreign_archive_id}/archive",
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
    assert [response.json()["code"] for response in responses] == [
        "CASE_MODULE_NOT_FOUND",
        "CASE_MODULE_NOT_FOUND",
        "CASE_MODULE_NOT_FOUND",
        "CASE_MODULE_NOT_FOUND",
        "CASE_MODULE_NOT_FOUND",
    ]


@pytest.mark.anyio
async def test_test_case_editing_endpoints_reject_cross_project_ids(
    client: AsyncClient,
    session: Session,
    case_api_context: dict[str, Any],
) -> None:
    project_id = str(case_api_context["project"].id)
    other_project_id = str(case_api_context["other_project"].id)
    headers = case_api_context["headers"]

    async def create_case_with_session(title: str) -> tuple[str, str]:
        create_response = await client.post(
            f"/api/v1/projects/{other_project_id}/test-cases",
            json={"title": title, "steps": []},
            headers=headers,
        )
        assert create_response.status_code == 200
        case_id = create_response.json()["id"]

        session_response = await client.post(
            f"/api/v1/projects/{other_project_id}/test-cases/{case_id}/edit-sessions",
            headers=headers,
        )
        assert session_response.status_code == 200
        return case_id, session_response.json()["id"]

    foreign_case_id, foreign_session_id = await create_case_with_session("Foreign case")
    abandon_case_id, abandon_session_id = await create_case_with_session("Foreign abandon case")

    responses = [
        await client.post(
            f"/api/v1/projects/{project_id}/test-cases/{foreign_case_id}/edit-sessions",
            headers=headers,
        ),
        await client.get(
            f"/api/v1/projects/{project_id}/test-cases/{foreign_case_id}/revisions",
            headers=headers,
        ),
        await client.put(
            f"/api/v1/projects/{project_id}/test-cases/{foreign_case_id}/edit-sessions/{foreign_session_id}/draft",
            json={"dirtyFields": {"title": "Cross-project change"}},
            headers=headers,
        ),
        await client.post(
            f"/api/v1/projects/{project_id}/test-cases/{foreign_case_id}/edit-sessions/{foreign_session_id}/finalize",
            json={"changeSummary": {"note": "Cross-project finalize"}},
            headers=headers,
        ),
        await client.post(
            f"/api/v1/projects/{project_id}/test-cases/{abandon_case_id}/edit-sessions/{abandon_session_id}/abandon",
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
    assert [response.json()["code"] for response in responses] == [
        "TEST_CASE_NOT_FOUND",
        "TEST_CASE_NOT_FOUND",
        "EDIT_SESSION_NOT_FOUND",
        "EDIT_SESSION_NOT_FOUND",
        "EDIT_SESSION_NOT_FOUND",
    ]

    session.expire_all()
    foreign_case = session.get(TestCaseModel, foreign_case_id)
    foreign_session = session.get(TestCaseEditSessionModel, foreign_session_id)
    abandon_session = session.get(TestCaseEditSessionModel, abandon_session_id)
    assert foreign_case is not None
    assert foreign_case.title == "Foreign case"
    assert foreign_session is not None
    assert foreign_session.status == "OPEN"
    assert foreign_session.dirty_fields == {}
    assert abandon_session is not None
    assert abandon_session.status == "OPEN"
