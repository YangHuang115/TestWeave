from typing import Any

import jsonschema

from testweave.core.errors import AppError
from testweave.modules.ai_capability.runtime.executors.base import BaseExecutor, ExecutorResult
from testweave.modules.ai_capability.runtime.provider import ModelProvider
from testweave.modules.ai_capability.runtime.skill_instructions import (
    resolve_skill_instructions,
)


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
        instructions = resolve_skill_instructions(package_files, skill_name)
        input_data = (
            resolved_input if isinstance(resolved_input, dict) else {"input": resolved_input}
        )

        input_schema = node_def.get("input_schema")
        if input_schema:
            try:
                jsonschema.validate(instance=input_data, schema=input_schema)
            except jsonschema.ValidationError as exc:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"Skill 输入校验 Schema 失败: {exc.message}",
                    status_code=400,
                ) from exc
            except jsonschema.SchemaError as exc:
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message=f"Skill 输入 Schema 非法: {exc.message}",
                    status_code=400,
                ) from exc

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
            input_data=input_data,
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
