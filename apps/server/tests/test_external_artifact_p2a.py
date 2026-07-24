import pytest
from httpx import ASGITransport, AsyncClient

from testweave.core.errors import AppError
from testweave.core.readiness import NotConfiguredReadinessProbe
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)


def test_artifact_schema_validator_test_point_set() -> None:
    valid_payload = {
        "points": [
            {
                "id": "TP-001",
                "title": "用户登录手机号校验",
                "description": "验证格式不合规的手机号被拒绝",
                "module": "账号模块",
            }
        ]
    }
    validated = ArtifactSchemaValidator.validate_artifact("test_point_set@1.0", valid_payload)
    assert validated == valid_payload

    invalid_payload = {
        "points": [
            {
                "description": "缺少 title 必填项",
            }
        ]
    }
    with pytest.raises(AppError) as exc_info:
        ArtifactSchemaValidator.validate_artifact("test_point_set@1.0", invalid_payload)
    assert exc_info.value.code == "INVALID_ARTIFACT_SCHEMA"


def test_artifact_schema_validator_test_case_set() -> None:
    valid_payload = {
        "cases": [
            {
                "id": "TC-001",
                "title": "测试正确密码登录",
                "precondition": "用户已注册",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "输入用户名密码并点击登录",
                        "expected": "跳转到首页",
                    }
                ],
                "expected_result": "登录成功",
            }
        ]
    }
    validated = ArtifactSchemaValidator.validate_artifact("test_case_set@1.0", valid_payload)
    assert validated == valid_payload

    invalid_payload = {
        "cases": [
            {
                "title": "缺少 steps 数组",
            }
        ]
    }
    with pytest.raises(AppError) as exc:
        ArtifactSchemaValidator.validate_artifact("test_case_set@1.0", invalid_payload)
    assert exc.value.code == "INVALID_ARTIFACT_SCHEMA"


def test_artifact_schema_validator_requirement_analysis() -> None:
    valid_payload = {
        "schemaVersion": "1.0",
        "stableKey": "requirement-analysis",
        "goal": "验证用户可以安全登录并获得正确权限",
        "inScope": ["账号密码登录"],
        "outOfScope": ["第三方 OAuth 登录"],
        "modules": [{"id": "account", "title": "账号模块", "description": "处理身份认证"}],
        "moduleRelations": [],
        "rules": [
            {"id": "RULE-001", "description": "连续失败五次后锁定", "evidenceRefs": ["SRC-001"]}
        ],
        "inferences": [
            {
                "id": "INF-001",
                "description": "锁定窗口可能为 30 分钟",
                "basis": "需求未明确窗口时间",
                "evidenceRefs": ["SRC-001"],
                "decision": "PENDING",
            }
        ],
        "questions": [
            {
                "id": "Q-001",
                "question": "锁定窗口是多少？",
                "blocking": True,
                "status": "PENDING",
                "answer": "",
                "decisionReason": "",
                "scope": "IN_SCOPE",
            }
        ],
        "risks": [
            {
                "id": "RISK-001",
                "title": "暴力破解",
                "description": "失败计数错误会降低安全性",
                "level": "HIGH",
                "testSignals": ["边界次数", "并发失败请求"],
                "evidenceRefs": ["RULE-001"],
            }
        ],
        "evidence": [
            {
                "id": "SRC-001",
                "sourceType": "REQUIREMENT",
                "sourceRef": "REQ-001",
                "quote": "连续失败五次后锁定账号",
            }
        ],
    }

    assert (
        ArtifactSchemaValidator.validate_artifact("requirement_analysis@1.0", valid_payload)
        == valid_payload
    )

    invalid_payload = dict(valid_payload)
    invalid_payload.pop("rules")
    with pytest.raises(AppError) as exc:
        ArtifactSchemaValidator.validate_artifact("requirement_analysis@1.0", invalid_payload)
    assert exc.value.code == "INVALID_ARTIFACT_SCHEMA"


def test_artifact_schema_validator_case_review_report() -> None:
    valid_payload = {
        "schemaVersion": "1.0",
        "stableKey": "case-review-report",
        "mode": "TRACEABLE",
        "gateRecommendation": "PASS_WITH_WARNINGS",
        "summary": "核心路径通过，存在一条可观察性警告",
        "caseResults": [{"caseRef": "TC-001", "status": "WARNING", "findingRefs": ["F-001"]}],
        "findings": [
            {
                "stableKey": "F-001",
                "severity": "WARNING",
                "caseRef": "TC-001",
                "fieldPath": "/steps/0/expected",
                "evidenceRefs": ["RULE-001"],
                "description": "预期结果不可直接观察",
                "suggestion": "补充页面提示或接口状态码",
                "decision": "PENDING",
                "decisionReason": "",
            }
        ],
        "coverage": {
            "ruleCoverage": 1.0,
            "testPointCoverage": 1.0,
            "uncoveredRefs": [],
        },
        "duplicateClusters": [],
        "unresolvedAssumptions": ["锁定窗口仍待确认"],
        "revisionRequests": [],
    }

    assert (
        ArtifactSchemaValidator.validate_artifact("test_case_review_report@1.0", valid_payload)
        == valid_payload
    )

    invalid_payload = {**valid_payload, "mode": "UNKNOWN"}
    with pytest.raises(AppError) as exc:
        ArtifactSchemaValidator.validate_artifact("test_case_review_report@1.0", invalid_payload)
    assert exc.value.code == "INVALID_ARTIFACT_SCHEMA"


def test_versioned_test_point_payload_requires_workbench_fields() -> None:
    incomplete_payload = {
        "schemaVersion": "1.0",
        "points": [{"stableKey": "TP-001", "title": "只有标题"}],
    }

    with pytest.raises(AppError) as exc:
        ArtifactSchemaValidator.validate_artifact("test_point_set@1.0", incomplete_payload)
    assert exc.value.code == "INVALID_ARTIFACT_SCHEMA"

    with pytest.raises(AppError) as empty_exc:
        ArtifactSchemaValidator.validate_artifact(
            "test_point_set@1.0",
            {"schemaVersion": "1.0", "points": []},
        )
    assert empty_exc.value.code == "INVALID_ARTIFACT_SCHEMA"


def test_versioned_test_case_payload_requires_numbered_observable_steps() -> None:
    incomplete_payload = {
        "schemaVersion": "1.0",
        "cases": [
            {
                "stableKey": "TC-001",
                "title": "登录成功",
                "module": "账号",
                "scope": "功能",
                "priority": "HIGH",
                "primaryTestPointRef": "TP-001",
                "ruleRefs": [],
                "preconditions": [],
                "testData": [],
                "steps": [{"action": "点击登录"}],
                "coreExpected": "登录成功",
                "observationPoints": [],
                "cleanupActions": [],
                "testMethod": "场景法",
                "assumptionRefs": [],
                "qualityPrecheck": {"status": "FAIL", "findings": []},
            }
        ],
    }

    with pytest.raises(AppError) as exc:
        ArtifactSchemaValidator.validate_artifact("test_case_set@1.0", incomplete_payload)
    assert exc.value.code == "INVALID_ARTIFACT_SCHEMA"


@pytest.mark.anyio
async def test_external_gateway_artifact_schema_api() -> None:
    app = create_app(readiness_probe=NotConfiguredReadinessProbe())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. GET /external/v1/artifact/schemas
        res_schemas = await client.get("/external/v1/artifact/schemas")
        assert res_schemas.status_code == 200
        data = res_schemas.json()
        assert "requirement_analysis@1.0" in data["supportedTypes"]
        assert "test_point_set@1.0" in data["supportedTypes"]
        assert "test_case_set@1.0" in data["supportedTypes"]
        assert "test_case_review_report@1.0" in data["supportedTypes"]

        # 2. POST /external/v1/artifact/validate 成功
        res_val = await client.post(
            "/external/v1/artifact/validate",
            json={
                "artifactType": "test_point_set@1.0",
                "payload": {"points": [{"title": "API Validated Point"}]},
            },
        )
        assert res_val.status_code == 200
        assert res_val.json()["valid"] is True

        # 3. POST /external/v1/artifact/validate 失败 422
        res_fail = await client.post(
            "/external/v1/artifact/validate",
            json={
                "artifactType": "test_point_set@1.0",
                "payload": {"points": [{}]},
            },
        )
        assert res_fail.status_code == 422
        assert res_fail.json()["code"] == "INVALID_ARTIFACT_SCHEMA"
