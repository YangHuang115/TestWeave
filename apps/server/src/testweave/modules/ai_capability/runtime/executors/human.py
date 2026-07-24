from typing import Any

import jsonschema

from testweave.core.errors import AppError
from testweave.modules.ai_capability.enums import HumanAction
from testweave.modules.ai_capability.runtime.executors.base import BaseExecutor, ExecutorResult
from testweave.modules.ai_capability.runtime.provider import ModelProvider


class HumanExecutor(BaseExecutor):
    """HUMAN Gate 交互节点执行器"""

    async def execute(
        self,
        node_id: str,
        node_def: dict[str, Any],
        resolved_input: Any,
        execution_snapshot: dict[str, Any],
        provider: ModelProvider,
        human_decision: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        # 没有任何人类决策时，挂起进入 WAITING_HUMAN
        if human_decision is None:
            input_dict = (
                resolved_input if isinstance(resolved_input, dict) else {"input": resolved_input}
            )
            return ExecutorResult(
                output={
                    "waiting_input": input_dict,
                    "prompt": node_def.get("prompt", "请确认上游节点输出"),
                },
                waiting_human=True,
            )

        # 处理人类决策提交
        action_str = human_decision.get("action", HumanAction.CONTINUE)
        if action_str == HumanAction.REJECT:
            raise AppError(
                code="RUN_HUMAN_REJECTED",
                message="用户拒绝了 Human Gate 环节确认",
                status_code=400,
            )

        decision_data = human_decision.get("decision", {})

        # Schema 校验人类决策
        decision_schema = node_def.get("decision_schema")
        if decision_schema:
            try:
                jsonschema.validate(instance=decision_data, schema=decision_schema)
            except jsonschema.ValidationError as ve:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"Human 决策不符合声明的 Schema: {ve.message}",
                    status_code=400,
                ) from ve

        # 决策通过：将结构化 decision 数据作为节点输出
        return ExecutorResult(
            output=decision_data
            if isinstance(decision_data, dict)
            else {"decision": decision_data},
            waiting_human=False,
        )
