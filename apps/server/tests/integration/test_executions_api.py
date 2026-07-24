"""M06 测试执行 API 集成测试（需要 PostgreSQL 一次性测试库）。

通过环境变量 TESTWEAVE_TEST_DATABASE_URL 指定 disposable 测试库；未设置时整文件跳过。

覆盖 START-HERE 五条关键规则在 API 层的端到端表现：
1. 创建执行任务原子冻结范围（totalCount == 来源用例数）。
2. 用例快照不可变（API 不直接暴露编辑入口）。
3. 每次执行新增一条历史记录（recordNo 自增=追加式）。
4. 资格仅按 owner/participant/admin_or_lead（非成员被 403）。
5. 所有用例至少执行一次后才能完成任务（未完成则 400）。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.cases.service import TestCaseService
from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.test_tasks.service import TestTaskService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService

pytestmark = pytest.mark.integration


@pytest.fixture
async def execution_integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    """准备 M06 执行 API 集成测试上下文（含已冻结用例的 CASE_DESIGN 来源任务）。"""
    admin_user = UserService.create_user(
        session,
        username="execapiadmin",
        email="execapiadmin@tw.com",
        display_name="Exec API Admin",
        password="pwd",
    )
    member_user = UserService.create_user(
        session,
        username="execapimember",
        email="execapimember@tw.com",
        display_name="Exec API Member",
        password="pwd",
    )
    UserService.create_user(
        session,
        username="execapiguest",
        email="execapiguest@tw.com",
        display_name="Exec API Guest",
        password="pwd",
    )
    session.commit()

    project = ProjectService.create_project(
        session,
        key="EXECAPIPROJ",
        name="Exec API Project",
        owner_id=admin_user.id,
        request_id="req-p",
    )
    session.commit()

    ProjectService.add_member(
        session,
        project_id=project.id,
        user_id=member_user.id,
        role_id="test_member",
        actor_id=admin_user.id,
        request_id="req-m",
    )
    session.commit()

    now_time = datetime.now(UTC)
    version = VersionService.create_version(
        session,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0",
        owner_id=admin_user.id,
        planned_start_at=now_time - timedelta(days=1),
        planned_end_at=now_time + timedelta(days=10),
        actor_id=admin_user.id,
        request_id="req-v",
    )
    session.commit()

    req = RequirementService.create_requirement(
        session,
        project_id=project.id,
        requirement_no="REQ-EAPI1",
        title="执行 API 需求",
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

    # CASE_DESIGN 来源任务（带 3 条用例）
    design = TestTaskService.create_task(
        session,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="设计任务-执行API",
        description="",
        priority="MEDIUM",
        owner_id=admin_user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=10),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=admin_user.id,
        request_id="r-d",
        requirement_id=req.id,
    )
    session.commit()
    for i in range(1, 4):
        TestCaseService.create_case(
            session,
            project_id=project.id,
            title=f"用例{i}",
            precondition=None,
            priority="MEDIUM",
            case_type="FUNCTIONAL",
            tags_json=[],
            test_data_note=None,
            note=None,
            steps=[{"action": f"步骤{i}", "expected_result": "ok"}],
            source_task_id=design.id,
            actor_id=admin_user.id,
            request_id=f"r-c{i}",
        )
    session.commit()

    # 额外：无用例的 CASE_DESIGN 任务（用于校验来源必须有用例）
    empty_design = TestTaskService.create_task(
        session,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="空设计任务",
        description="",
        priority="MEDIUM",
        owner_id=admin_user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=10),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=admin_user.id,
        request_id="r-de",
        requirement_id=req.id,
    )
    session.commit()

    async def _login(username: str) -> dict[str, Any]:
        res = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": username, "password": "pwd"},
        )
        cookies = res.cookies
        return {
            "cookies": cookies,
            "headers": {"X-CSRF-Token": cookies.get("xsrf_token")},
        }

    return {
        "project": project,
        "version": version,
        "requirement": req,
        "design": design,
        "empty_design": empty_design,
        "admin_user": admin_user,
        "member_user": member_user,
        "admin_session": await _login("execapiadmin"),
        "member_session": await _login("execapimember"),
        "guest_session": await _login("execapiguest"),
    }


async def _transition(
    client: AsyncClient,
    session_dict: dict[str, Any],
    project_id: str,
    task_id: str,
    target: str,
    row_version: int,
) -> tuple[int, dict[str, Any]]:
    res = await client.post(
        f"/api/v1/projects/{project_id}/test-tasks/{task_id}/transitions",
        json={"targetStatus": target, "rowVersion": row_version},
        **session_dict,
    )
    return res.status_code, res.json()


@pytest.mark.anyio
async def test_execution_api_lifecycle(
    client: AsyncClient, execution_integration_context: dict[str, Any]
) -> None:
    ctx = execution_integration_context
    pid = str(ctx["project"].id)
    design_id = str(ctx["design"].id)
    admin = ctx["admin_session"]

    now_time = datetime.now(UTC)
    planned_end = now_time + timedelta(days=5)

    # 1. 创建执行任务：原子冻结 3 条用例（创建后 DRAFT，row_version=1）
    create_payload = {
        "sourceDesignTaskId": design_id,
        "title": "执行任务-集成",
        "ownerId": str(ctx["admin_user"].id),
        "plannedEndAt": planned_end.isoformat(),
        "priority": "MEDIUM",
        "buildVersion": "1.0.0",
        "testEnvironment": {"name": "staging"},
        "idempotencyKey": "exec-lifecycle-1",
    }
    res = await client.post(f"/api/v1/projects/{pid}/test-executions", json=create_payload, **admin)
    assert res.status_code == 201
    task = res.json()
    assert task["status"] == "DRAFT"
    assert task["totalCount"] == 3
    assert task["notRunCount"] == 3
    assert task["passedCount"] == 0
    task_id = task["id"]
    row_version = 1  # 创建即 DRAFT，row_version 初值

    # 幂等：相同键返回同一任务
    res2 = await client.post(
        f"/api/v1/projects/{pid}/test-executions", json=create_payload, **admin
    )
    assert res2.status_code == 201
    assert res2.json()["id"] == task_id

    # 2. 列表与详情
    res = await client.get(f"/api/v1/projects/{pid}/test-executions", **admin)
    assert res.status_code == 200
    assert any(t["id"] == task_id for t in res.json()["items"])

    res = await client.get(f"/api/v1/projects/{pid}/test-executions/{task_id}", **admin)
    assert res.status_code == 200
    assert res.json()["totalCount"] == 3

    # 3. 用例行冻结
    res = await client.get(f"/api/v1/projects/{pid}/test-executions/{task_id}/cases", **admin)
    assert res.status_code == 200
    cases = res.json()["items"]
    assert res.json()["total"] == 3
    assert all(c["currentResult"] is None for c in cases)
    case_ids = [c["id"] for c in cases]

    # 4. 非项目成员访问被拒
    res = await client.get(
        f"/api/v1/projects/{pid}/test-executions/{task_id}", **ctx["guest_session"]
    )
    assert res.status_code == 403

    # 5. 来源无用例被拒
    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions",
        json={
            "sourceDesignTaskId": str(ctx["empty_design"].id),
            "title": "空来源执行",
            "ownerId": str(ctx["admin_user"].id),
            "plannedEndAt": planned_end.isoformat(),
            "priority": "MEDIUM",
            "idempotencyKey": "exec-empty",
        },
        **admin,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "EXECUTION_SOURCE_TASK_HAS_NO_CASES"

    # 6. 流转 DRAFT -> READY
    code, body = await _transition(client, admin, pid, task_id, "READY", row_version)
    assert code == 200
    row_version = body["rowVersion"]
    assert body["status"] == "READY"

    # 7. 记录首条用例（READY -> IN_PROGRESS，recordNo 自增）
    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/cases/{case_ids[0]}/records",
        json={"result": "PASSED", "idempotencyKey": "rec-1"},
        **admin,
    )
    assert res.status_code == 200
    rec = res.json()
    assert rec["recordNo"] == 1
    assert rec["result"] == "PASSED"

    res = await client.get(f"/api/v1/projects/{pid}/test-executions/{task_id}", **admin)
    assert res.json()["status"] == "IN_PROGRESS"

    # 8. 仍有未执行用例时完成被拒（EXECUTION_COMPLETION_NOT_RUN_EXISTS）
    res = await client.post(f"/api/v1/projects/{pid}/test-executions/{task_id}/complete", **admin)
    assert res.status_code == 400
    assert res.json()["code"] == "EXECUTION_COMPLETION_NOT_RUN_EXISTS"

    # 9. 追加式：再记同一条用例，recordNo 自增且不覆盖
    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/cases/{case_ids[0]}/records",
        json={"result": "FAILED", "actualResult": "实际报错", "idempotencyKey": "rec-2"},
        **admin,
    )
    assert res.status_code == 200
    assert res.json()["recordNo"] == 2

    res = await client.get(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/cases/{case_ids[0]}/records",
        **admin,
    )
    assert res.status_code == 200
    assert res.json()["total"] == 2  # 追加式，不覆盖

    # 10. 批量通过剩余用例
    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/batch-pass",
        json={"executionCaseIds": [case_ids[1], case_ids[2]], "idempotencyKey": "bp-1"},
        **admin,
    )
    assert res.status_code == 200
    bp = res.json()
    assert bp["total"] == 2
    assert bp["succeeded"] == 2
    assert bp["failed"] == 0

    # 11. completion-preview 显示全部已执行
    res = await client.get(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/completion-preview", **admin
    )
    assert res.status_code == 200
    preview = res.json()
    assert preview["notRun"] == 0
    assert preview["total"] == 3

    # 12. 完成任务
    res = await client.post(f"/api/v1/projects/{pid}/test-executions/{task_id}/complete", **admin)
    assert res.status_code == 200
    assert res.json()["status"] == "COMPLETED"

    # 13. 重新打开（需要原因 + admin/lead）
    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/reopen",
        json={"reasonText": "需要补充回归测试"},
        **admin,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "IN_PROGRESS"

    # 14. 导出 Excel
    res = await client.post(f"/api/v1/projects/{pid}/test-executions/{task_id}/exports", **admin)
    assert res.status_code == 200
    export = res.json()
    assert export["status"] == "COMPLETED"
    assert export["fileObjectKey"]


@pytest.mark.anyio
async def test_execution_record_permission_denied(
    client: AsyncClient, execution_integration_context: dict[str, Any]
) -> None:
    """非成员不能读取/记录执行结果（资格校验在 API 层为 403）。"""
    ctx = execution_integration_context
    pid = str(ctx["project"].id)
    design_id = str(ctx["design"].id)

    res = await client.post(
        f"/api/v1/projects/{pid}/test-executions",
        json={
            "sourceDesignTaskId": design_id,
            "title": "权限执行任务",
            "ownerId": str(ctx["admin_user"].id),
            "plannedEndAt": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "priority": "MEDIUM",
            "idempotencyKey": "exec-perm-1",
        },
        **ctx["admin_session"],
    )
    assert res.status_code == 201
    task_id = res.json()["id"]

    # 流转到 READY（创建后 row_version=1）
    code, _ = await _transition(client, ctx["admin_session"], pid, task_id, "READY", 1)
    assert code == 200

    # 非成员尝试读取用例 -> 403
    res = await client.get(
        f"/api/v1/projects/{pid}/test-executions/{task_id}/cases",
        **ctx["guest_session"],
    )
    assert res.status_code == 403
