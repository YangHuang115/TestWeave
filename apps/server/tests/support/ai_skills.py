import json
import textwrap
import uuid
from typing import Any

from sqlalchemy.orm import Session

from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    REQUIREMENT_ANALYSIS_SCHEMA_V1,
    TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
    WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
    WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
)
from testweave.modules.ai_capability.schemas import FileMapping
from testweave.modules.ai_skill.service import SkillRegistryService
from testweave.modules.ai_test_design.constants import (
    BUILTIN_INPUT_SCHEMA,
    HUMAN_DECISION_SCHEMA,
)

_SKILL_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "requirement-analysis": REQUIREMENT_ANALYSIS_SCHEMA_V1,
    "test-point-generation": WORKBENCH_TEST_POINT_SET_SCHEMA_V1,
    "test-case-generation": WORKBENCH_TEST_CASE_SET_SCHEMA_V1,
    "test-case-review": TEST_CASE_REVIEW_REPORT_SCHEMA_V1,
}

_SKILL_PROMPTS = {
    "requirement-analysis": "你是 TestWeave 需求分析智能体。只输出符合 Schema 的候选稿。",
    "test-point-generation": "你是 TestWeave 测试点设计智能体。只输出符合 Schema 的候选稿。",
    "test-case-generation": "你是 TestWeave 测试用例设计智能体。只输出符合 Schema 的候选稿。",
    "test-case-review": "你是 TestWeave 用例评审智能体。只输出符合 Schema 的候选稿。",
}

_UPSTREAM_NODES = {
    "test-point-generation": ["requirement_analysis"],
    "test-case-generation": ["requirement_analysis", "test_points"],
    "test-case-review": ["requirement_analysis", "test_points", "test_cases"],
}
_GATE_INPUT_KEYS = {
    "test-point-generation": "acceptedRequirementAnalysis",
    "test-case-generation": "acceptedTestPoints",
    "test-case-review": "acceptedTestCases",
}


def publish_workbench_skills(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    for code, output_schema in _SKILL_OUTPUT_SCHEMAS.items():
        synced = SkillRegistryService.sync_draft(
            db=db,
            project_id=project_id,
            user_id=user_id,
            effective_scopes=["skill:sync"],
            files=_build_files(code, output_schema),
            request_id=f"test-sync-{code}",
        )
        SkillRegistryService.publish_version(
            db=db,
            project_id=project_id,
            skill_id=uuid.UUID(synced["skillId"]),
            version_id=uuid.UUID(synced["versionId"]),
            actor_id=user_id,
            request_id=f"test-publish-{code}",
        )


def _build_files(code: str, output_schema: dict[str, Any]) -> list[FileMapping]:
    manifest = textwrap.dedent(
        f"""\
        protocol_version: "1.0"
        skill:
          id: "{code}"
          version: "1.0.0"
          name: "{code}"
          description: "测试环境中注册的四阶段工作台 Skill。"
          prompt: "prompt.md"
          input_schema: "input.schema.json"
          output_schema: "output.schema.json"
          model_policy: "quality_first"
          allowed_tools: []
          required_permissions:
            - "project.read"
          side_effect_level: "L1"
        """
    )
    skill_md = textwrap.dedent(
        f"""\
        ---
        name: {code}
        description: 为 TestWeave 测试环境提供结构化候选稿；仅在四阶段工作台测试中使用。
        ---

        # {code}

        读取 prompt.md 和 Schema，且只提交 Candidate。
        """
    )
    return [
        FileMapping(path="manifest.yaml", content=manifest),
        FileMapping(path="SKILL.md", content=skill_md),
        FileMapping(path="prompt.md", content=_SKILL_PROMPTS[code]),
        FileMapping(
            path="input.schema.json",
            content=json.dumps(_build_runtime_input_schema(code)),
        ),
        FileMapping(
            path="output.schema.json",
            content=json.dumps(output_schema, ensure_ascii=False),
        ),
    ]


def _build_runtime_input_schema(code: str) -> dict[str, Any]:
    if code == "requirement-analysis":
        return BUILTIN_INPUT_SCHEMA

    upstream_nodes = _UPSTREAM_NODES[code]
    gate_key = _GATE_INPUT_KEYS[code]
    properties: dict[str, Any] = {
        gate_key: HUMAN_DECISION_SCHEMA,
        "originalContext": BUILTIN_INPUT_SCHEMA,
        "acceptedUpstreamContext": {
            "type": "object",
            "properties": {
                node_id: {
                    "type": "array",
                    "items": {"type": "object"},
                    "minItems": 1,
                }
                for node_id in upstream_nodes
            },
            "required": upstream_nodes,
            "additionalProperties": False,
        },
        "acceptedUpstreamManifest": {
            "type": "object",
            "properties": {
                node_id: {
                    "type": "object",
                    "required": ["set_revision_id", "set_hash", "item_count"],
                    "properties": {
                        "set_revision_id": {"type": "string", "minLength": 1},
                        "set_hash": {"type": "string", "minLength": 1},
                        "item_count": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                }
                for node_id in upstream_nodes
            },
            "required": upstream_nodes,
            "additionalProperties": False,
        },
    }
    required = [
        gate_key,
        "originalContext",
        "acceptedUpstreamContext",
        "acceptedUpstreamManifest",
    ]
    if code == "test-case-review":
        properties["reviewMode"] = {
            "type": "string",
            "enum": ["TRACEABLE", "INTRINSIC"],
        }
        required.append("reviewMode")
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
