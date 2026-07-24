from typing import Any, ClassVar

from testweave.core.errors import AppError
from testweave.modules.ai_capability.runtime.executors.base import BaseExecutor, ExecutorResult
from testweave.modules.ai_capability.runtime.provider import ModelProvider


class TransformExecutor(BaseExecutor):
    """TRANSFORM 白名单纯数据转换执行器"""

    ALLOWED_OPERATIONS: ClassVar[set[str]] = {"identity", "pick", "merge_arrays", "rename_keys"}

    async def execute(
        self,
        node_id: str,
        node_def: dict[str, Any],
        resolved_input: Any,
        execution_snapshot: dict[str, Any],
        provider: ModelProvider,
        human_decision: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        operation = node_def.get("operation", "identity")

        if operation not in self.ALLOWED_OPERATIONS:
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message=f"不赞成的 Transform 操作 '{operation}'，仅支持 {self.ALLOWED_OPERATIONS}",
                status_code=400,
            )

        output: dict[str, Any] = {}

        if operation == "identity":
            output = (
                resolved_input if isinstance(resolved_input, dict) else {"data": resolved_input}
            )

        elif operation == "pick":
            keys = node_def.get("config", {}).get("keys", [])
            if isinstance(resolved_input, dict):
                output = {k: resolved_input[k] for k in keys if k in resolved_input}

        elif operation == "merge_arrays":
            # 数组合并
            merged = []
            if isinstance(resolved_input, dict):
                for v in resolved_input.values():
                    if isinstance(v, list):
                        merged.extend(v)
            output = {"items": merged}

        elif operation == "rename_keys":
            mapping = node_def.get("config", {}).get("mapping", {})
            if isinstance(resolved_input, dict):
                output = {mapping.get(k, k): v for k, v in resolved_input.items()}

        return ExecutorResult(output=output)
