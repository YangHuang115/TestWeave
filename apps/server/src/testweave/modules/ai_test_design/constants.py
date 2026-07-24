from typing import Any

from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    REQUIREMENT_ANALYSIS_SCHEMA_V1,
    TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
    WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
    WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
)

BUILTIN_CAPABILITY_NAMESPACE = "testweave.official"
BUILTIN_CAPABILITY_CODE = "ai_test_design_workbench"
BUILTIN_CAPABILITY_VERSION = "1.0.0"

STAGE_DEFINITIONS: dict[str, dict[str, str]] = {
    "requirement-analysis": {
        "nodeId": "requirement_analysis",
        "gateNodeId": "requirement_analysis_gate",
        "artifactType": "requirement_analysis@1.0",
        "label": "需求分析",
    },
    "test-points": {
        "nodeId": "test_points",
        "gateNodeId": "test_points_gate",
        "artifactType": "test_point_set@1.0",
        "label": "测试点",
    },
    "test-cases": {
        "nodeId": "test_cases",
        "gateNodeId": "test_cases_gate",
        "artifactType": "test_case_set@1.0",
        "label": "测试用例",
    },
    "case-review": {
        "nodeId": "case_review",
        "gateNodeId": "case_review_gate",
        "artifactType": "test_case_review_report@1.0",
        "label": "用例评审",
    },
}

NODE_TO_STAGE = {definition["nodeId"]: key for key, definition in STAGE_DEFINITIONS.items()}

WORKFLOW_DAG: dict[str, list[str]] = {
    "requirement_analysis": ["test_points"],
    "test_points": ["test_cases"],
    "test_cases": ["case_review"],
    "case_review": [],
}

HUMAN_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "acceptedSetRevisionId",
        "acceptedSetHash",
        "acceptedItems",
        "decisionSnapshot",
    ],
    "properties": {
        "acceptedSetRevisionId": {"type": "string", "minLength": 1},
        "acceptedSetHash": {"type": "string", "minLength": 1},
        "acceptedItems": {"type": "array", "items": {"type": "object"}},
        "decisionSnapshot": {"type": "object"},
    },
    "additionalProperties": False,
}

BUILTIN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["task", "requirement", "attachments", "reviewMode"],
    "properties": {
        "task": {
            "type": "object",
            "required": ["id", "taskNo", "title", "description", "testGoal", "excludedScope"],
            "properties": {
                "id": {"type": "string"},
                "taskNo": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "testGoal": {"type": ["string", "null"]},
                "excludedScope": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "requirement": {
            "type": "object",
            "required": [
                "id",
                "requirementNo",
                "title",
                "description",
                "acceptanceCriteria",
                "priority",
                "updatedAt",
            ],
            "properties": {
                "id": {"type": "string"},
                "requirementNo": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "acceptanceCriteria": {"type": ["string", "null"]},
                "priority": {"type": "string"},
                "updatedAt": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "attachments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "fileName",
                    "contentType",
                    "description",
                    "sha256",
                    "extractedText",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "fileName": {"type": "string"},
                    "contentType": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "sha256": {"type": "string"},
                    "extractedText": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
        },
        "reviewMode": {"type": "string", "enum": ["TRACEABLE", "INTRINSIC"]},
    },
    "additionalProperties": False,
}

REQUIREMENT_ANALYSIS_INSTRUCTIONS = """你是 TestWeave 需求分析智能体。只依据输入中的需求、任务与附件来源元数据生成结构化分析，不得虚构已确认事实。把未明确内容放入 inferences 或 questions；会阻塞测试设计的问题必须标记 blocking=true。每条规则、风险与关系都要使用 evidenceRefs 建立来源追踪。输出必须符合 requirement_analysis@1.0 Schema。"""

TEST_POINT_INSTRUCTIONS = """你是 TestWeave 测试点设计智能体。只使用服务端提供的、已经人工接受的需求分析完整集合生成测试点。测试点必须可独立追踪到规则、问题与模块关系；测试方法要写明选择原因。allowCaseGeneration 默认由风险与可执行性判断，但最终选择权属于用户。输出必须符合 test_point_set@1.0 Schema。"""

TEST_CASE_INSTRUCTIONS = """你是 TestWeave 测试用例设计智能体。只为人工确认 allowCaseGeneration=true 的测试点生成用例。每条用例只能有一个 primaryTestPointRef 和一个 coreExpected；步骤必须包含可执行动作及对应可观察预期，测试数据要具体。输出必须符合 test_case_set@1.0 Schema。"""

CASE_REVIEW_INSTRUCTIONS = """你是 TestWeave 用例评审智能体。按输入的 TRACEABLE 或 INTRINSIC 模式评审已人工接受的完整用例集合。Finding 必须定位到具体 fieldPath，提供证据和定向建议；评审只生成报告和修订请求，绝不能直接改写用例。输出必须符合 test_case_review_report@1.0 Schema。"""


def _projection(collection_pointer: str, artifact_type: str) -> dict[str, Any]:
    return {
        "collection_pointer": collection_pointer,
        "artifact_type": artifact_type,
        "review_policy": "HUMAN_REQUIRED",
    }


BUILTIN_WORKFLOW: dict[str, Any] = {
    "nodes": {
        "requirement_analysis": {
            "type": "SKILL",
            "name": "生成需求分析",
            "skill": "requirement-analysis",
            "input": "capability.input",
            "output_schema": REQUIREMENT_ANALYSIS_SCHEMA_V1,
            "artifact_projection": _projection("", "requirement_analysis@1.0"),
            "model_policy": "quality_first",
        },
        "requirement_analysis_gate": {
            "type": "HUMAN",
            "name": "确认需求分析",
            "input": "requirement_analysis.output",
            "prompt": "请回答阻塞问题并确认需求分析后继续",
            "decision_schema": HUMAN_DECISION_SCHEMA,
        },
        "test_points": {
            "type": "SKILL",
            "name": "生成测试点",
            "skill": "test-point-generation",
            "input": {
                "acceptedRequirementAnalysis": "requirement_analysis_gate.output",
                "originalContext": "capability.input",
            },
            "accepted_upstream_nodes": ["requirement_analysis"],
            "output_schema": WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
            "artifact_projection": _projection("/points", "test_point_set@1.0"),
            "model_policy": "quality_first",
        },
        "test_points_gate": {
            "type": "HUMAN",
            "name": "确认测试点",
            "input": "test_points.output",
            "prompt": "请编辑并选择允许生成用例的测试点后继续",
            "decision_schema": HUMAN_DECISION_SCHEMA,
        },
        "test_cases": {
            "type": "SKILL",
            "name": "生成测试用例",
            "skill": "test-case-generation",
            "input": {
                "acceptedTestPoints": "test_points_gate.output",
                "originalContext": "capability.input",
            },
            "accepted_upstream_nodes": ["requirement_analysis", "test_points"],
            "output_schema": WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
            "artifact_projection": _projection("/cases", "test_case_set@1.0"),
            "model_policy": "quality_first",
        },
        "test_cases_gate": {
            "type": "HUMAN",
            "name": "确认测试用例",
            "input": "test_cases.output",
            "prompt": "请确认候选测试用例后进入评审",
            "decision_schema": HUMAN_DECISION_SCHEMA,
        },
        "case_review": {
            "type": "SKILL",
            "name": "评审测试用例",
            "skill": "test-case-review",
            "input": {
                "acceptedTestCases": "test_cases_gate.output",
                "reviewMode": "capability.input#/reviewMode",
                "originalContext": "capability.input",
            },
            "accepted_upstream_nodes": [
                "requirement_analysis",
                "test_points",
                "test_cases",
            ],
            "output_schema": TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
            "artifact_projection": _projection("", "test_case_review_report@1.0"),
            "model_policy": "quality_first",
        },
        "case_review_gate": {
            "type": "HUMAN",
            "name": "确认评审报告",
            "input": "case_review.output",
            "prompt": "请处理评审 Finding 并保存最终评审决策",
            "decision_schema": HUMAN_DECISION_SCHEMA,
        },
    }
}

BUILTIN_PACKAGE_FILES: dict[str, Any] = {
    "workflow.json": BUILTIN_WORKFLOW,
    "schemas/input.schema.json": BUILTIN_INPUT_SCHEMA,
    "schemas/requirement_analysis.schema.json": REQUIREMENT_ANALYSIS_SCHEMA_V1,
    "schemas/test_point_set.schema.json": WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
    "schemas/test_case_set.schema.json": WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
    "schemas/test_case_review_report.schema.json": TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
    "skills/requirement-analysis/SKILL.md": REQUIREMENT_ANALYSIS_INSTRUCTIONS,
    "skills/test-point-generation/SKILL.md": TEST_POINT_INSTRUCTIONS,
    "skills/test-case-generation/SKILL.md": TEST_CASE_INSTRUCTIONS,
    "skills/test-case-review/SKILL.md": CASE_REVIEW_INSTRUCTIONS,
}
