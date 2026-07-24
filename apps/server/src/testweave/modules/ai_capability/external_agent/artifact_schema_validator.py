from typing import Any

import jsonschema
from jsonschema.exceptions import ValidationError

from testweave.core.errors import AppError


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _strict_object(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


SCHEMA_VERSION = {"type": "string", "const": "1.0"}

REQUIREMENT_ANALYSIS_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    **_strict_object(
        {
            "schemaVersion": SCHEMA_VERSION,
            "stableKey": {"type": "string", "minLength": 1},
            "goal": {"type": "string", "minLength": 1},
            "inScope": _string_array(),
            "outOfScope": _string_array(),
            "modules": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "title": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                    }
                ),
            },
            "moduleRelations": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "sourceModuleRef": {"type": "string", "minLength": 1},
                        "targetModuleRef": {"type": "string", "minLength": 1},
                        "relationType": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                        "evidenceRefs": _string_array(),
                    }
                ),
            },
            "rules": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "evidenceRefs": _string_array(),
                    }
                ),
            },
            "inferences": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "basis": {"type": "string"},
                        "evidenceRefs": _string_array(),
                        "decision": {
                            "type": "string",
                            "enum": ["PENDING", "ACCEPTED", "REJECTED"],
                        },
                    }
                ),
            },
            "questions": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "question": {"type": "string", "minLength": 1},
                        "blocking": {"type": "boolean"},
                        "status": {
                            "type": "string",
                            "enum": [
                                "PENDING",
                                "ANSWERED",
                                "ASSUMPTION_ACCEPTED",
                                "DEFERRED",
                                "OUT_OF_SCOPE",
                            ],
                        },
                        "answer": {"type": "string"},
                        "decisionReason": {"type": "string"},
                        "scope": {"type": "string", "enum": ["IN_SCOPE", "OUT_OF_SCOPE"]},
                    }
                ),
            },
            "risks": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "title": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "level": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                        "testSignals": _string_array(),
                        "evidenceRefs": _string_array(),
                    }
                ),
            },
            "evidence": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "sourceType": {
                            "type": "string",
                            "enum": ["REQUIREMENT", "ATTACHMENT", "HUMAN_DECISION"],
                        },
                        "sourceRef": {"type": "string", "minLength": 1},
                        "quote": {"type": "string"},
                    }
                ),
            },
        }
    ),
}

TEST_POINT_PROPERTIES: dict[str, Any] = {
    "stableKey": {"type": "string", "minLength": 1},
    "title": {"type": "string", "minLength": 1},
    "description": {"type": "string"},
    "module": {"type": "string", "minLength": 1},
    "scope": {"type": "string", "minLength": 1},
    "preconditions": _string_array(),
    "coreAction": {"type": "string", "minLength": 1},
    "coreExpected": {"type": "string", "minLength": 1},
    "variables": {
        "type": "array",
        "items": _strict_object(
            {
                "name": {"type": "string", "minLength": 1},
                "partitions": _string_array(),
            }
        ),
    },
    "testMethod": {"type": "string", "minLength": 1},
    "testMethodReason": {"type": "string", "minLength": 1},
    "risk": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
    "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
    "ruleRefs": _string_array(),
    "questionRefs": _string_array(),
    "moduleRelationRefs": _string_array(),
    "allowCaseGeneration": {"type": "boolean"},
    # 兼容既有 Gateway Client 的字段。
    "id": {"type": "string"},
}
TEST_POINT_REQUIRED = [key for key in TEST_POINT_PROPERTIES if key != "id"]
STRICT_TEST_POINT_ITEM_SCHEMA_V1 = _strict_object(
    TEST_POINT_PROPERTIES, required=TEST_POINT_REQUIRED
)

WORKBENCH_TEST_POINT_SET_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    **_strict_object(
        {
            "schemaVersion": SCHEMA_VERSION,
            "points": {
                "type": "array",
                "minItems": 1,
                "items": STRICT_TEST_POINT_ITEM_SCHEMA_V1,
            },
        }
    ),
}

TEST_POINT_SET_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["points"],
    "properties": {
        "schemaVersion": SCHEMA_VERSION,
        "version": {"type": "string"},
        "points": {
            "type": "array",
            "items": _strict_object(TEST_POINT_PROPERTIES, required=["title"]),
        },
    },
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"required": ["schemaVersion"]},
            "then": {
                "required": ["schemaVersion", "points"],
                "properties": {
                    "points": {
                        "type": "array",
                        "minItems": 1,
                        "items": STRICT_TEST_POINT_ITEM_SCHEMA_V1,
                    }
                },
            },
        }
    ],
}

TEST_CASE_PROPERTIES: dict[str, Any] = {
    "stableKey": {"type": "string", "minLength": 1},
    "title": {"type": "string", "minLength": 1},
    "module": {"type": "string", "minLength": 1},
    "scope": {"type": "string", "minLength": 1},
    "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
    "primaryTestPointRef": {"type": "string", "minLength": 1},
    "ruleRefs": _string_array(),
    "preconditions": _string_array(),
    "testData": {
        "type": "array",
        "items": _strict_object(
            {
                "name": {"type": "string", "minLength": 1},
                "value": {"type": "string"},
                "purpose": {"type": "string"},
            }
        ),
    },
    "steps": {
        "type": "array",
        "minItems": 1,
        "items": _strict_object(
            {
                "stepNo": {"type": "integer", "minimum": 1},
                "action": {"type": "string", "minLength": 1},
                "expected": {"type": "string", "minLength": 1},
                # 兼容旧字段。
                "step_number": {"type": "integer", "minimum": 1},
            },
            required=["action"],
        ),
    },
    "coreExpected": {"type": "string", "minLength": 1},
    "observationPoints": _string_array(),
    "cleanupActions": _string_array(),
    "testMethod": {"type": "string", "minLength": 1},
    "assumptionRefs": _string_array(),
    "qualityPrecheck": _strict_object(
        {
            "status": {"type": "string", "enum": ["PASS", "WARNING", "FAIL"]},
            "findings": _string_array(),
        }
    ),
    # 兼容既有 Gateway Client 的字段。
    "id": {"type": "string"},
    "precondition": {"type": "string"},
    "expected_result": {"type": "string"},
}
TEST_CASE_REQUIRED = [
    key for key in TEST_CASE_PROPERTIES if key not in {"id", "precondition", "expected_result"}
]
STRICT_TEST_CASE_PROPERTIES = {
    **TEST_CASE_PROPERTIES,
    "steps": {
        "type": "array",
        "minItems": 1,
        "items": _strict_object(
            {
                "stepNo": {"type": "integer", "minimum": 1},
                "action": {"type": "string", "minLength": 1},
                "expected": {"type": "string", "minLength": 1},
            }
        ),
    },
}
STRICT_TEST_CASE_ITEM_SCHEMA_V1 = _strict_object(
    STRICT_TEST_CASE_PROPERTIES, required=TEST_CASE_REQUIRED
)

WORKBENCH_TEST_CASE_SET_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    **_strict_object(
        {
            "schemaVersion": SCHEMA_VERSION,
            "cases": {
                "type": "array",
                "minItems": 1,
                "items": STRICT_TEST_CASE_ITEM_SCHEMA_V1,
            },
        }
    ),
}

TEST_CASE_SET_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["cases"],
    "properties": {
        "schemaVersion": SCHEMA_VERSION,
        "version": {"type": "string"},
        "cases": {
            "type": "array",
            "items": _strict_object(TEST_CASE_PROPERTIES, required=["title", "steps"]),
        },
    },
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"required": ["schemaVersion"]},
            "then": {
                "required": ["schemaVersion", "cases"],
                "properties": {
                    "cases": {
                        "type": "array",
                        "minItems": 1,
                        "items": STRICT_TEST_CASE_ITEM_SCHEMA_V1,
                    }
                },
            },
        }
    ],
}

TEST_CASE_REVIEW_REPORT_SCHEMA_V1: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    **_strict_object(
        {
            "schemaVersion": SCHEMA_VERSION,
            "stableKey": {"type": "string", "minLength": 1},
            "mode": {"type": "string", "enum": ["TRACEABLE", "INTRINSIC"]},
            "gateRecommendation": {
                "type": "string",
                "enum": ["PASS", "PASS_WITH_WARNINGS", "BLOCK"],
            },
            "summary": {"type": "string"},
            "caseResults": {
                "type": "array",
                "items": _strict_object(
                    {
                        "caseRef": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "enum": ["PASS", "WARNING", "FAIL"]},
                        "findingRefs": _string_array(),
                    }
                ),
            },
            "findings": {
                "type": "array",
                "items": _strict_object(
                    {
                        "stableKey": {"type": "string", "minLength": 1},
                        "severity": {
                            "type": "string",
                            "enum": ["INFO", "WARNING", "ERROR", "CRITICAL"],
                        },
                        "caseRef": {"type": "string", "minLength": 1},
                        "fieldPath": {"type": "string", "minLength": 1},
                        "evidenceRefs": _string_array(),
                        "description": {"type": "string", "minLength": 1},
                        "suggestion": {"type": "string"},
                        "decision": {
                            "type": "string",
                            "enum": ["PENDING", "ACCEPTED", "REJECTED", "EDITED"],
                        },
                        "decisionReason": {"type": "string"},
                    }
                ),
            },
            "coverage": _strict_object(
                {
                    "ruleCoverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "testPointCoverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "uncoveredRefs": _string_array(),
                }
            ),
            "duplicateClusters": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "caseRefs": _string_array(),
                        "reason": {"type": "string"},
                    }
                ),
            },
            "unresolvedAssumptions": _string_array(),
            "revisionRequests": {
                "type": "array",
                "items": _strict_object(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "caseRef": {"type": "string", "minLength": 1},
                        "fieldPath": {"type": "string", "minLength": 1},
                        "instruction": {"type": "string", "minLength": 1},
                        "status": {
                            "type": "string",
                            "enum": ["DRAFT", "CONFIRMED", "APPLIED", "REJECTED"],
                        },
                    }
                ),
            },
        }
    ),
}

REGISTERED_SCHEMAS: dict[str, dict[str, Any]] = {
    "requirement_analysis@1.0": REQUIREMENT_ANALYSIS_SCHEMA_V1,
    "test_point_set@1.0": TEST_POINT_SET_SCHEMA_V1,
    "test_case_set@1.0": TEST_CASE_SET_SCHEMA_V1,
    "test_case_review_report@1.0": TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
}

WORKBENCH_SCHEMAS: dict[str, dict[str, Any]] = {
    "requirement_analysis@1.0": REQUIREMENT_ANALYSIS_SCHEMA_V1,
    "test_point_set@1.0": WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
    "test_case_set@1.0": WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
    "test_case_review_report@1.0": TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
}


class ArtifactSchemaValidator:
    @staticmethod
    def get_supported_types() -> list[str]:
        return list(REGISTERED_SCHEMAS)

    @staticmethod
    def get_schema(artifact_type: str) -> dict[str, Any]:
        if artifact_type not in REGISTERED_SCHEMAS:
            raise AppError(
                code="UNSUPPORTED_ARTIFACT_TYPE",
                message=f"不支持的 Candidate Artifact 类型: {artifact_type}",
                status_code=400,
            )
        return REGISTERED_SCHEMAS[artifact_type]

    @staticmethod
    def get_workbench_schema(artifact_type: str) -> dict[str, Any]:
        if artifact_type not in WORKBENCH_SCHEMAS:
            raise AppError(
                code="UNSUPPORTED_ARTIFACT_TYPE",
                message=f"不支持的工作台 Artifact 类型: {artifact_type}",
                status_code=400,
            )
        return WORKBENCH_SCHEMAS[artifact_type]

    @staticmethod
    def extract_items(artifact_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if artifact_type == "test_point_set@1.0":
            return list(payload.get("points", []))
        if artifact_type == "test_case_set@1.0":
            return list(payload.get("cases", []))
        if artifact_type in {
            "requirement_analysis@1.0",
            "test_case_review_report@1.0",
        }:
            return [payload]
        ArtifactSchemaValidator.get_schema(artifact_type)
        return []

    @classmethod
    def validate_artifact(cls, artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = cls.get_schema(artifact_type)
        try:
            jsonschema.validate(instance=payload, schema=schema)
        except ValidationError as e:
            raise AppError(
                code="INVALID_ARTIFACT_SCHEMA",
                message=f"Artifact 数据不符合 {artifact_type} Schema 规范: {e.message}",
                status_code=422,
            ) from e
        return payload
