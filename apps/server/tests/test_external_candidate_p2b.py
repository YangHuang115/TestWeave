import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.db.models import AICapability, Project, ProjectMember, User
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.candidate_submission_service import (
    CandidateSubmissionService,
)
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)


@pytest.fixture
def candidate_test_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"editor_{uuid.uuid4().hex[:6]}@testweave.com",
        username=f"editor_{uuid.uuid4().hex[:6]}",
        display_name="Editor User",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name=f"Candidate Project {uuid.uuid4().hex[:6]}",
        key=f"PRJ_{uuid.uuid4().hex[:4]}".upper(),
        owner_id=admin.id,
    )
    db.add(project)
    db.commit()

    pm = ProjectMember(
        project_id=project.id,
        user_id=admin.id,
        role_id="project_editor",
    )
    db.add(pm)

    capability = AICapability(
        project_id=project.id,
        scope="PROJECT",
        namespace="testweave",
        code=f"cap_{uuid.uuid4().hex[:6]}",
        name="Candidate Submission Capability",
        category="TEST_POINT_GENERATION",
    )
    db.add(capability)
    db.commit()

    return {
        "admin": admin,
        "project": project,
        "capability": capability,
    }


def test_candidate_submission_service_scope_and_schema_validation(
    db: Session, candidate_test_context: dict
) -> None:
    admin = candidate_test_context["admin"]
    project = candidate_test_context["project"]
    cap = candidate_test_context["capability"]

    # 1. 缺乏 revision:candidate 权限时拒绝
    with pytest.raises(AppError) as exc_scope:
        CandidateSubmissionService.submit_candidate_revision(
            db,
            token_project_id=project.id,
            user_id=admin.id,
            effective_scopes=["workspace:spec"],
            capability_id=cap.id,
            artifact_type="test_point_set@1.0",
            payload={"points": [{"title": "Point"}]},
        )
    assert exc_scope.value.code == "SCOPE_PERMISSION_DENIED"

    # 2. Schema 不合规拦截
    with pytest.raises(AppError) as exc_schema:
        CandidateSubmissionService.submit_candidate_revision(
            db,
            token_project_id=project.id,
            user_id=admin.id,
            effective_scopes=["revision:candidate"],
            capability_id=cap.id,
            artifact_type="test_point_set@1.0",
            payload={"points": [{}]},
        )
    assert exc_schema.value.code == "INVALID_ARTIFACT_SCHEMA"

    # 3. 正常提交返回结果
    res = CandidateSubmissionService.submit_candidate_revision(
        db,
        token_project_id=project.id,
        user_id=admin.id,
        effective_scopes=["revision:candidate"],
        capability_id=cap.id,
        artifact_type="test_point_set@1.0",
        payload={"points": [{"title": "Valid Point"}]},
    )
    assert res["status"] == "SUBMITTED"
    assert res["itemCount"] == 1


def test_candidate_submission_service_rejects_auto_publish(
    db: Session, candidate_test_context: dict
) -> None:
    admin = candidate_test_context["admin"]
    project = candidate_test_context["project"]
    cap = candidate_test_context["capability"]

    with pytest.raises(AppError) as exc:
        CandidateSubmissionService.submit_candidate_revision(
            db,
            token_project_id=project.id,
            user_id=admin.id,
            effective_scopes=["revision:candidate"],
            capability_id=cap.id,
            artifact_type="requirement_analysis@1.0",
            payload={
                "schemaVersion": "1.0",
                "stableKey": "requirement-analysis",
                "goal": "验证登录需求",
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
            auto_publish=True,
        )

    assert exc.value.code == "EXTERNAL_AUTO_PUBLISH_FORBIDDEN"
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_external_gateway_candidate_api_endpoints(
    db: Session, candidate_test_context: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()

    admin = candidate_test_context["admin"]
    project = candidate_test_context["project"]
    cap = candidate_test_context["capability"]

    from testweave.api.dependencies.database import get_db

    def _override_get_db():
        yield db

    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    app.dependency_overrides[get_db] = _override_get_db

    _tok_obj, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Candidate Submission Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["revision:candidate"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. 提交候选 Candidate Revision
        res_sub = await client.post(
            "/external/v1/revision/candidates",
            json={
                "capabilityId": str(cap.id),
                "artifactType": "test_case_set@1.0",
                "payload": {
                    "cases": [
                        {
                            "title": "Generated Test Case",
                            "steps": [{"action": "Action 1"}],
                        }
                    ]
                },
                "summary": "External Client Candidate Submission Test",
            },
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_sub.status_code == 200
        sub_data = res_sub.json()
        assert sub_data["status"] == "SUBMITTED"
        sub_id = sub_data["submissionId"]

        # 2. 测试 GET /external/v1/candidates/{submissionId} 回查接口
        res_get_cand = await client.get(
            f"/external/v1/candidates/{sub_id}",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_get_cand.status_code == 200
        assert res_get_cand.json()["submissionId"] == sub_id

        # 3. 外接 Candidate 不允许请求自动发布
        res_pub = await client.post(
            "/external/v1/revision/candidates",
            json={
                "capabilityId": str(cap.id),
                "artifactType": "test_case_set@1.0",
                "autoPublish": True,
                "payload": {
                    "cases": [
                        {
                            "title": "Auto Published Test Case",
                            "steps": [{"action": "Action 1"}],
                        }
                    ]
                },
            },
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_pub.status_code == 422

        # 2. 注册过程依赖附件
        res_att = await client.post(
            "/external/v1/attachments/register",
            json={
                "submissionId": sub_id,
                "fileName": "execution_trace.log",
                "fileSize": 1024,
                "mimeType": "text/plain",
            },
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res_att.status_code == 200
        assert res_att.json()["fileName"] == "execution_trace.log"

    get_external_agent_config.cache_clear()
