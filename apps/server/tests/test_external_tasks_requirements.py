import uuid
from datetime import UTC
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import (
    Project,
    ProjectMember,
    Requirement,
    TestTask,
    TestTaskRequirement,
    User,
)
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


@pytest.fixture
def task_req_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"tr_admin_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"tr_admin_{uuid.uuid4().hex[:6]}",
        display_name="Task Requirement Admin",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Task Req Project {uuid.uuid4().hex[:6]}",
        key=f"PRJ_{uuid.uuid4().hex[:4]}".upper(),
        owner_id=admin.id,
    )
    db.add(project)
    db.commit()

    pm = ProjectMember(
        project_id=project.id,
        user_id=admin.id,
        role_id="project_admin",
    )
    db.add(pm)

    req = Requirement(
        project_id=project.id,
        requirement_no="REQ-10001",
        requirement_no_normalized="req-10001",
        title="每日签到需求",
        description="每日签到功能详细需求文档正文...",
        acceptance_criteria="用户每日签到增加积分",
        priority="HIGH",
        status="PUBLISHED",
    )
    db.add(req)
    db.commit()

    from datetime import datetime

    now = datetime.now(UTC)
    task = TestTask(
        project_id=project.id,
        version_id=project.id,
        task_no="TASK-0727fb",
        task_type="CASE_DESIGN",
        status="IN_PROGRESS",
        title="每日签到用例设计",
        description="设计每日签到测试用例",
        priority="MEDIUM",
        owner_id=admin.id,
        planned_start_at=now,
        planned_end_at=now,
    )
    db.add(task)
    db.commit()

    t_link = TestTaskRequirement(
        task_id=task.id,
        requirement_id=req.id,
        linked_by=admin.id,
    )
    db.add(t_link)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "requirement": req,
        "task": task,
    }


@pytest.mark.anyio
async def test_external_tasks_and_requirements_api(
    db: Session, task_req_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = task_req_context["admin"]
    project = task_req_context["project"]
    task = task_req_context["task"]
    req = task_req_context["requirement"]

    from testweave.api.dependencies.database import get_db

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Task Req Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["test_task.read", "requirement.read"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": f"Bearer {raw_token}"}

        # 1. 测试 GET /external/v1/tasks
        res_tasks = await client.get("/external/v1/tasks", headers=headers)
        assert res_tasks.status_code == 200
        tasks_data = res_tasks.json()["tasks"]
        assert len(tasks_data) > 0
        t0 = tasks_data[0]
        assert t0["id"] == str(task.id)
        assert t0["key"] == "TASK-0727fb"
        assert t0["requirementId"] == str(req.id)
        assert t0["requirementKey"] == "REQ-10001"
        assert t0["requirementTitle"] == "每日签到需求"

        # 2. 测试 GET /external/v1/tasks/{taskId} 任务详情
        res_detail = await client.get(f"/external/v1/tasks/{task.id}", headers=headers)
        assert res_detail.status_code == 200
        task_detail = res_detail.json()
        assert task_detail["id"] == str(task.id)
        assert task_detail["requirementKey"] == "REQ-10001"
        assert len(task_detail["requirements"]) == 1

        # 3. 测试 GET /external/v1/tasks/{taskId}/requirements
        res_task_reqs = await client.get(
            f"/external/v1/tasks/{task.id}/requirements", headers=headers
        )
        assert res_task_reqs.status_code == 200
        assert len(res_task_reqs.json()["requirements"]) == 1
        assert res_task_reqs.json()["requirements"][0]["key"] == "REQ-10001"

        # 4. 测试 GET /external/v1/requirements 需求列表
        res_req_list = await client.get("/external/v1/requirements", headers=headers)
        assert res_req_list.status_code == 200
        assert len(res_req_list.json()["requirements"]) == 1
        assert res_req_list.json()["requirements"][0]["key"] == "REQ-10001"

        # 5. 测试 GET /external/v1/requirements/{requirementId} 需求详情
        res_req_detail = await client.get(f"/external/v1/requirements/{req.id}", headers=headers)
        assert res_req_detail.status_code == 200
        assert "每日签到功能详细需求文档正文" in res_req_detail.json()["description"]

        # 6. 测试上传附件并尝试提取正文与下载
        from testweave.db.models import RequirementAttachment

        att_obj = RequirementAttachment(
            project_id=project.id,
            requirement_id=req.id,
            original_filename="sample_spec.txt",
            content_type="text/plain",
            size_bytes=100,
            sha256="dummy_sha",
            storage_key=f"{project.id}/{req.id}/sample_spec.txt",
            status="ACTIVE",
        )
        db.add(att_obj)
        db.commit()

        # 模拟写入文件
        from pathlib import Path

        from testweave.core.config import get_settings
        from testweave.infrastructure.storage import LocalStorageProvider

        storage = LocalStorageProvider(get_settings().storage_local_dir)
        full_p = Path(storage._get_filepath(att_obj.storage_key))
        full_p.parent.mkdir(parents=True, exist_ok=True)
        full_p.write_text(
            "这是从 sample_spec.txt 文件中自动提取的需求详细正文内容！", encoding="utf-8"
        )

        res_extracted = await client.get(f"/external/v1/requirements/{req.id}", headers=headers)
        assert res_extracted.status_code == 200
        assert (
            "这是从 sample_spec.txt 文件中自动提取的需求详细正文内容！"
            in res_extracted.json()["contentDoc"]
        )

        # 7. 测试附件下载端点
        down_url = f"/external/v1/requirements/{req.id}/attachments/{att_obj.id}/download"
        res_down = await client.get(down_url, headers=headers)
        assert res_down.status_code == 200
        assert "这是从 sample_spec.txt" in res_down.text

        # 8. 测试不存在的 Task ID 返回 404
        fake_id = uuid.uuid4()
        res_404 = await client.get(f"/external/v1/tasks/{fake_id}", headers=headers)
        assert res_404.status_code == 404
        assert res_404.json()["code"] == "TASK_NOT_FOUND"

    get_external_agent_config.cache_clear()
