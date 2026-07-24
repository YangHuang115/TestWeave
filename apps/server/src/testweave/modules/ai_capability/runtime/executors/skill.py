from typing import Any

import jsonschema

from testweave.core.errors import AppError
from testweave.modules.ai_capability.runtime.executors.base import BaseExecutor, ExecutorResult
from testweave.modules.ai_capability.runtime.provider import ModelProvider


class SkillExecutor(BaseExecutor):
    """SKILL 节点执行器"""

    async def execute(
        self,
        node_id: str,
        node_def: dict[str, Any],
        resolved_input: Any,
        execution_snapshot: dict[str, Any],
        provider: ModelProvider,
        human_decision: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        package_files = execution_snapshot.get("package_files", {})

        # 获取配置与 manifest 对应 instructions 文件
        skill_name = node_def.get("skill", "")
        instructions_path = f"skills/{skill_name}/SKILL.md" if skill_name else "SKILL.md"
        instructions = (
            package_files.get(instructions_path)
            or package_files.get("SKILL.md")
            or "You are an AI assistant."
        )

        # 获取输出 Schema
        output_schema = node_def.get("output_schema") or {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "additionalProperties": False,
        }

        model_policy = node_def.get("model_policy", "quality_first")

        # 调用模型
        res = await provider.invoke_structured_json(
            instructions=instructions,
            input_data=resolved_input
            if isinstance(resolved_input, dict)
            else {"input": resolved_input},
            output_schema=output_schema,
            model_policy=model_policy,
        )

        # 校验响应 JSON 符合节点声明的 output_schema
        try:
            jsonschema.validate(instance=res.content_json, schema=output_schema)
        except jsonschema.ValidationError as ve:
            raise AppError(
                code="RUN_OUTPUT_SCHEMA_INVALID",
                message=f"模型输出校验 Schema 失败: {ve.message}",
                status_code=400,
            ) from ve

        return ExecutorResult(
            output=res.content_json,
            provider_name=res.provider_name,
            model_name=res.model_name,
            usage_snapshot={
                "prompt_tokens": res.prompt_tokens,
                "completion_tokens": res.completion_tokens,
                "total_tokens": res.total_tokens,
            },
        )
