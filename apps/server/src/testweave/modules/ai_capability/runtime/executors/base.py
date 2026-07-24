from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from testweave.modules.ai_capability.runtime.provider import ModelProvider


class ExecutorResult(BaseModel):
    """节点执行器统一返回数据"""

    output: dict[str, Any]
    validator_results: dict[str, Any] | None = None
    provider_name: str | None = None
    model_name: str | None = None
    usage_snapshot: dict[str, Any] | None = None
    waiting_human: bool = False
    retryable: bool = True
    error_code: str | None = None
    error_summary: str | None = None


class BaseExecutor(ABC):
    """Workflow 节点执行器抽象基类"""

    @abstractmethod
    async def execute(
        self,
        node_id: str,
        node_def: dict[str, Any],
        resolved_input: Any,
        execution_snapshot: dict[str, Any],
        provider: ModelProvider,
        human_decision: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """执行节点逻辑"""
        pass
