import asyncio
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import AICapability, Project, ProjectMember, User
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


@pytest.fixture
def idempotency_test_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"idem_admin_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"idem_admin_{uuid.uuid4().hex[:6]}",
        display_name="Idempotency Admin",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Idempotency Project {uuid.uuid4().hex[:6]}",
        key=f"IDEM_{uuid.uuid4().hex[:4]}".upper(),
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

    capability = AICapability(
        project_id=project.id,
        scope="PROJECT",
        namespace="testweave",
        code=f"cap_{uuid.uuid4().hex[:6]}",
        name="Idempotency Capability",
        category="TEST_POINT_GENERATION",
    )
    db.add(capability)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "capability": capability,
    }


@pytest.mark.anyio
async def test_idempotency_sequential_and_concurrent_replay(
    db: Session, idempotency_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = idempotency_test_context["admin"]
    project = idempotency_test_context["project"]
    cap = idempotency_test_context["capability"]

    from testweave.api.dependencies.database import get_db

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Idempotency Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["revision:candidate"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {
            "Authorization": f"Bearer {raw_token}",
            "Idempotency-Key": "codex:TASK-000001:req10001-analysis-points:v2:ca232a42",
        }

        payload = {
            "capabilityId": str(cap.id),
            "artifactType": "test_point_set@1.0",
            "payload": {
                "version": "1.0",
                "points": [{"title": "正常签到"}, {"title": "重复签到"}],
            },
            "summary": "Idempotency Replay Test",
        }

        # 1. 顺序重放 10 次
        first_submission_id = None
        for i in range(10):
            res = await client.post(
                "/external/v1/revision/candidates", json=payload, headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            if i == 0:
                first_submission_id = data["submissionId"]
                assert "Idempotency-Replay" not in res.headers
            else:
                assert data["submissionId"] == first_submission_id
                assert res.headers.get("Idempotency-Replay") == "true"

        # 2. 相同键、不同请求内容 -> 返回 409 IDEMPOTENCY_KEY_REUSED
        different_payload = dict(payload)
        different_payload["summary"] = "Mutated summary for 409 test"
        res_409 = await client.post(
            "/external/v1/revision/candidates", json=different_payload, headers=headers
        )
        assert res_409.status_code == 409
        assert res_409.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

        # 3. Header 与 Body 键冲突 -> 返回 400 IDEMPOTENCY_KEY_MISMATCH
        mismatch_payload = dict(payload)
        mismatch_payload["idempotencyKey"] = "conflict-body-key"
        res_400 = await client.post(
            "/external/v1/revision/candidates", json=mismatch_payload, headers=headers
        )
        assert res_400.status_code == 400
        assert res_400.json()["code"] == "IDEMPOTENCY_KEY_MISMATCH"

        # 4. 同一请求并发提交 10 次
        concurrent_headers = {
            "Authorization": f"Bearer {raw_token}",
            "Idempotency-Key": "concurrent:test:key:12345",
        }
        concurrent_payload = {
            "capabilityId": str(cap.id),
            "artifactType": "test_point_set@1.0",
            "payload": {"version": "1.0", "points": [{"title": "并发节点"}]},
        }

        async def _submit_task():
            async with AsyncClient(transport=transport, base_url="http://testserver") as c:
                return await c.post(
                    "/external/v1/revision/candidates",
                    json=concurrent_payload,
                    headers=concurrent_headers,
                )

        tasks = [_submit_task() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        submission_ids = set()
        for r in results:
            assert r.status_code == 200
            submission_ids.add(r.json()["submissionId"])

        # 确保只产生了一个 Candidate 记录与提交 ID
        assert len(submission_ids) == 1

        # 5. 验证 Candidate 回查能查到持久化数据
        final_sub_id = next(iter(submission_ids))
        res_cand = await client.get(
            f"/external/v1/candidates/{final_sub_id}",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_cand.status_code == 200
        assert res_cand.json()["submissionId"] == final_sub_id
