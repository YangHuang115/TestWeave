from typing import Any

import jsonschema

from testweave.modules.ai_capability.runtime.executors.base import BaseExecutor, ExecutorResult
from testweave.modules.ai_capability.runtime.provider import ModelProvider


class ValidatorExecutor(BaseExecutor):
    """VALIDATOR 声明式校验节点执行器"""

    async def execute(
        self,
        node_id: str,
        node_def: dict[str, Any],
        resolved_input: Any,
        execution_snapshot: dict[str, Any],
        provider: ModelProvider,
        human_decision: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        rules = node_def.get("rules", [])
        input_schema = node_def.get("input_schema")

        validation_errors = []

        # 1. 结构化 Schema 校验
        if input_schema:
            try:
                jsonschema.validate(instance=resolved_input, schema=input_schema)
            except jsonschema.ValidationError as ve:
                validation_errors.append(f"Schema 校验错误: {ve.message}")

        # 2. 示例规则: every_item_has_source_reference
        if "every_item_has_source_reference" in rules:
            items: list[Any] = []
            if isinstance(resolved_input, dict):
                items = resolved_input.get("test_points") or resolved_input.get("items") or []
            elif isinstance(resolved_input, list):
                items = resolved_input

            for idx, item in enumerate(items):
                if isinstance(item, dict):
                    has_ref = bool(
                        item.get("source_reference")
                        or item.get("requirement_reference")
                        or item.get("source_ref")
                    )
                    if not has_ref:
                        validation_errors.append(
                            f"测试点索引 {idx} (ID: {item.get('id', idx)}) 缺失源需求引用"
                        )

        if validation_errors:
            validator_results = {
                "valid": False,
                "errors": validation_errors,
            }
            return ExecutorResult(
                output=resolved_input
                if isinstance(resolved_input, dict)
                else {"input": resolved_input},
                validator_results=validator_results,
                waiting_human=False,
                retryable=False,
                error_code="RUN_VALIDATOR_FAILED",
                error_summary="; ".join(validation_errors),
            )

        # 校验成功：透传输入数据为输出，并记录成功报告
        validator_results = {
            "valid": True,
            "errors": [],
        }
        output = resolved_input if isinstance(resolved_input, dict) else {"input": resolved_input}
        return ExecutorResult(
            output=output,
            validator_results=validator_results,
        )
