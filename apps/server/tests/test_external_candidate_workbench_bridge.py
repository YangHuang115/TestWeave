import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.db.models import (
    AIArtifactSetRevision,
    AITestDesignRecord,
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
def workbench_bridge_context(db: Session, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    admin = User(
        email=f"editor_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"editor_{uuid.uuid4().hex[:6]}",
        display_name="Editor User",
        hashed_password="dummy_hash",
        status="active",
        is_system_admin=True,
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Bridge Project {uuid.uuid4().hex[:6]}",
        key=f"PRJ_{uuid.uuid4().hex[:4]}".upper(),
        owner_id=admin.id,
    )
    db.add(project)
    db.flush()

    pm = ProjectMember(
        project_id=project.id,
        user_id=admin.id,
        role_id="project_admin",
    )
    db.add(pm)

    req_no = f"REQ-{uuid.uuid4().hex[:4]}".upper()
    req = Requirement(
        project_id=project.id,
        requirement_no=req_no,
        requirement_no_normalized=req_no.upper(),
        title="游戏战斗系统需求",
        status="APPROVED",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(req)
    db.flush()

    from testweave.db.models import Version

    version = Version(
        project_id=project.id,
        key="V1.0.0",
        key_normalized="V1.0.0",
        name="v1.0.0",
        owner_id=admin.id,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(version)
    db.flush()

    from datetime import UTC, datetime

    now = datetime.now(UTC)

    task = TestTask(
        project_id=project.id,
        version_id=version.id,
        task_no="TASK-BRIDGE-001",
        title="游戏战斗功能测试设计任务",
        status="IN_PROGRESS",
        task_type="CASE_DESIGN",
        owner_id=admin.id,
        planned_start_at=now,
        planned_end_at=now,
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(task)
    db.flush()

    ttr = TestTaskRequirement(
        task_id=task.id,
        requirement_id=req.id,
    )
    db.add(ttr)

    db.commit()

    token_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        project_id=project.id,
        user_id=admin.id,
        name="Bridge Test Token",
        scopes=["revision:candidate", "test_task.read", "requirement.read"],
    )

    return {
        "admin": admin,
        "project": project,
        "requirement": req,
        "task": task,
        "raw_token": raw_token,
        "token_obj": token_obj,
    }


@pytest.mark.anyio
async def test_external_candidate_submission_auto_mounts_workbench_run(
    db: Session, workbench_bridge_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_AI_RUNTIME__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    app = create_app()
    project = workbench_bridge_context["project"]
    task = workbench_bridge_context["task"]
    raw_token = workbench_bridge_context["raw_token"]

    headers = {
        "Authorization": f"Bearer {raw_token}",
        "Idempotency-Key": f"bridge-test-{uuid.uuid4().hex}",
    }

    payload = {
        "taskKey": task.task_no,
        "artifactType": "requirement_analysis@1.0",
        "payload": {
            "schemaVersion": "1.0",
            "stableKey": "requirement-analysis",
            "goal": "验证游戏战斗系统功能",
            "inScope": ["战斗伤害计算"],
            "outOfScope": ["UI 动画展现"],
            "modules": [{"id": "battle", "title": "战斗模块", "description": "处理伤害与冷却"}],
            "moduleRelations": [],
            "rules": [
                {"id": "RULE-001", "description": "冷却时间为 5 秒", "evidenceRefs": ["SRC-001"]}
            ],
            "inferences": [],
            "questions": [],
            "risks": [],
            "evidence": [
                {
                    "id": "SRC-001",
                    "sourceType": "REQUIREMENT",
                    "sourceRef": "REQ-001",
                    "quote": "冷却时间固定为 5 秒",
                }
            ],
        },
    }

    from testweave.api.dependencies.database import get_db

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 外部 Agent 调用 candidates 接口提交需求分析候选产物
        res_sub = await ac.post("/external/v1/revision/candidates", json=payload, headers=headers)
        assert res_sub.status_code == 200, res_sub.text
        data_sub = res_sub.json()
        assert data_sub["status"] == "SUBMITTED"
        assert data_sub["taskId"] == str(task.id)
        assert data_sub["recordId"] is not None
        assert data_sub["setRevisionId"] is not None

        # 2. 验证后端自动生成了 AITestDesignRecord
        records = list(
            db.scalars(
                select(AITestDesignRecord).where(AITestDesignRecord.task_id == task.id)
            ).all()
        )
        assert len(records) == 1
        record = records[0]
        assert record.record_no == 1
        assert str(record.id) == data_sub["recordId"]

        # 3. 验证自动创建并挂载了 AIArtifactSetRevision
        sets = list(
            db.scalars(
                select(AIArtifactSetRevision).where(
                    AIArtifactSetRevision.run_id == record.run_id,
                    AIArtifactSetRevision.producer_node_id == "requirement_analysis",
                )
            ).all()
        )
        assert len(sets) == 1
        assert str(sets[0].id) == data_sub["setRevisionId"]

        # 4. 模拟 Web 端刷新 AI 测试设计工作台（即使是普通开发者视角也可以拉取该任务的记录列表）
        normal_user = User(
            email=f"dev_{uuid.uuid4().hex[:6]}@testweave.com",
            username=f"dev_{uuid.uuid4().hex[:6]}",
            display_name="Dev User",
            hashed_password="dummy_hash",
            status="active",
            is_system_admin=False,
        )
        db.add(normal_user)
        db.flush()

        normal_pm = ProjectMember(
            project_id=project.id,
            user_id=normal_user.id,
            role_id="project_admin",
        )
        db.add(normal_pm)
        db.commit()

        from testweave.api.dependencies.auth import get_current_user
        from testweave.api.dependencies.database import get_db

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: normal_user

        res_web = await ac.get(
            f"/api/v1/projects/{project.id}/test-tasks/{task.id}/ai-design/records"
        )
        assert res_web.status_code == 200, res_web.text
        data_web = res_web.json()
        assert len(data_web["items"]) == 1
        assert data_web["items"][0]["id"] == str(record.id)
        assert data_web["items"][0]["recordNo"] == 1

        # 5. 模拟 Web 端恢复指定生成链与阶段产物状态
        res_detail = await ac.get(
            f"/api/v1/projects/{project.id}/test-tasks/{task.id}/ai-design/records/{record.id}?stage=requirement-analysis"
        )
        assert res_detail.status_code == 200, res_detail.text
        data_detail = res_detail.json()
        assert data_detail["stage"]["key"] == "requirement-analysis"
        assert data_detail["stage"]["candidateRevision"] is not None
        assert len(data_detail["stage"]["revisionHistory"]) >= 1

        app.dependency_overrides.clear()
        get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_external_candidate_submission_resolves_task_by_requirement_key_and_snake_case(
    db: Session, workbench_bridge_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_AI_RUNTIME__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    app = create_app()
    req = workbench_bridge_context["requirement"]
    task = workbench_bridge_context["task"]
    raw_token = workbench_bridge_context["raw_token"]

    headers = {
        "Authorization": f"Bearer {raw_token}",
        "Idempotency-Key": f"bridge-test-snake-{uuid.uuid4().hex}",
    }

    # 模拟外部 Agent 使用 requirement_key (需求单号) 提交蛇形 JSON 结构
    payload = {
        "requirement_key": req.requirement_no,
        "artifact_type": "test_point_set@1.0",
        "payload": {
            "schemaVersion": "1.0",
            "points": [
                {
                    "id": "TP-001",
                    "stableKey": "TP-001",
                    "module": "battle",
                    "title": "战斗技能 CD 逻辑验证",
                    "description": "验证 CD 冷却状态下按键响应",
                    "scope": "IN_SCOPE",
                    "priority": "HIGH",
                    "preconditions": ["技能初始就绪"],
                    "coreAction": "点击释放技能",
                    "coreExpected": "技能进入 CD 冷却",
                    "variables": [],
                    "testMethod": "MANUAL",
                    "testMethodReason": "手工点选验证",
                    "ruleRefs": [],
                    "questionRefs": [],
                    "moduleRelationRefs": [],
                    "risk": "LOW",
                    "allowCaseGeneration": True,
                }
            ],
        },
    }

    from testweave.api.dependencies.database import get_db

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/external/v1/revision/candidates", json=payload, headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "SUBMITTED"
        assert data["taskId"] == str(task.id)
        assert data["recordId"] is not None

    app.dependency_overrides.clear()
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_external_candidate_submission_auto_increments_round_when_accepted(
    db: Session, workbench_bridge_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_AI_RUNTIME__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    app = create_app()
    task = workbench_bridge_context["task"]
    raw_token = workbench_bridge_context["raw_token"]

    headers = {
        "Authorization": f"Bearer {raw_token}",
        "Idempotency-Key": f"bridge-test-round-1-{uuid.uuid4().hex}",
    }

    payload = {
        "taskKey": task.task_no,
        "artifactType": "requirement_analysis@1.0",
        "payload": {
            "schemaVersion": "1.0",
            "stableKey": "requirement-analysis",
            "goal": "第 1 轮目标",
            "inScope": ["战斗伤害计算"],
            "outOfScope": ["UI 动画展现"],
            "modules": [{"id": "battle", "title": "战斗模块", "description": "第1轮说明"}],
            "moduleRelations": [],
            "rules": [],
            "inferences": [],
            "questions": [],
            "risks": [],
            "evidence": [],
        },
    }

    from testweave.api.dependencies.database import get_db

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 提交第一轮
        res1 = await ac.post("/external/v1/revision/candidates", json=payload, headers=headers)
        assert res1.status_code == 200, res1.text
        data1 = res1.json()
        rec_id1 = data1["recordId"]

        records = db.query(AITestDesignRecord).where(AITestDesignRecord.task_id == task.id).all()
        assert len(records) == 1
        assert records[0].record_no == 1

        # 3. 再次提交同一阶段，应当自动递增生成第 2 轮
        payload2 = dict(payload)
        payload2["payload"]["goal"] = "第 2 轮目标"
        headers2 = {
            "Authorization": f"Bearer {raw_token}",
            "Idempotency-Key": f"bridge-test-round-2-{uuid.uuid4().hex}",
        }
        res2 = await ac.post("/external/v1/revision/candidates", json=payload2, headers=headers2)
        assert res2.status_code == 200, res2.text
        data2 = res2.json()
        rec_id2 = data2["recordId"]

        # 断言生成了新的一轮
        assert rec_id1 != rec_id2
        records_after = (
            db.query(AITestDesignRecord)
            .where(AITestDesignRecord.task_id == task.id)
            .order_by(AITestDesignRecord.record_no)
            .all()
        )
        assert len(records_after) == 2
        assert records_after[0].record_no == 1
        assert records_after[1].record_no == 2
        assert str(records_after[1].id) == rec_id2

        # 验证轮次标题中成功带入了 Gateway 的 submission ID
        assert "网关提交 (ID:" in records_after[0].title
        assert "网关提交 (ID:" in records_after[1].title

    app.dependency_overrides.clear()
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_ai_test_design_list_records_filters_empty_history(
    db: Session, workbench_bridge_context: dict[str, Any]
) -> None:
    from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
    from testweave.modules.ai_test_design.service import AiTestDesignService

    project = workbench_bridge_context["project"]
    task = workbench_bridge_context["task"]
    admin = workbench_bridge_context["admin"]

    # 1. 连续创建 3 轮 record（均为没有任何候选集产物的空轮次）
    _r1, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=admin.id,
        actor_permissions={"agent.use"},
        idempotency_key="idemp-empty-1",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    _r2, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=admin.id,
        actor_permissions={"agent.use"},
        idempotency_key="idemp-empty-2",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )
    r3, _ = AiTestDesignService.create_record(
        db=db,
        project_id=project.id,
        task_id=task.id,
        actor_id=admin.id,
        actor_permissions={"agent.use"},
        idempotency_key="idemp-empty-3",
        runtime_settings=AIRuntimeSettings(TESTWEAVE_AI_RUNTIME__ENABLED=True),
    )

    # 2. 拉取列表，断言：旧的 r1, r2 应该由于为空被过滤，仅保留最新的一轮 r3！
    recs = AiTestDesignService.list_records(db, project.id, task.id, admin.id)
    assert len(recs) == 1
    assert recs[0].id == r3.id


@pytest.mark.anyio
async def test_delete_ai_test_design_record_endpoint(
    db: Session, workbench_bridge_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    monkeypatch.setenv("TESTWEAVE_AI_RUNTIME__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    app = create_app()
    project = workbench_bridge_context["project"]
    task = workbench_bridge_context["task"]
    raw_token = workbench_bridge_context["raw_token"]
    admin = workbench_bridge_context["admin"]

    headers = {
        "Authorization": f"Bearer {raw_token}",
        "Idempotency-Key": f"bridge-test-del-{uuid.uuid4().hex}",
    }

    # 1. 提交产物，创建第 1 轮
    payload = {
        "taskKey": task.task_no,
        "artifactType": "requirement_analysis@1.0",
        "payload": {
            "schemaVersion": "1.0",
            "stableKey": "requirement-analysis",
            "goal": "删除测试目标",
            "inScope": [],
            "outOfScope": [],
            "modules": [],
            "moduleRelations": [],
            "rules": [],
            "inferences": [],
            "questions": [],
            "risks": [],
            "evidence": [],
        },
    }

    from testweave.api.dependencies.auth import get_current_user
    from testweave.api.dependencies.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res_sub = await ac.post("/external/v1/revision/candidates", json=payload, headers=headers)
        assert res_sub.status_code == 200
        data_sub = res_sub.json()
        rec_id = data_sub["recordId"]

        # 断言数据库里确实生成了该记录
        records = (
            db.query(AITestDesignRecord).where(AITestDesignRecord.id == uuid.UUID(rec_id)).all()
        )
        assert len(records) == 1

        # 2. 调用 DELETE 接口删除该轮次
        res_del = await ac.delete(
            f"/api/v1/projects/{project.id}/test-tasks/{task.id}/ai-design/records/{rec_id}"
        )
        assert res_del.status_code == 204

        # 3. 断言数据库中 record 已被彻底物理删除
        records_after = (
            db.query(AITestDesignRecord).where(AITestDesignRecord.id == uuid.UUID(rec_id)).all()
        )
        assert len(records_after) == 0

    app.dependency_overrides.clear()
    get_external_agent_config.cache_clear()
