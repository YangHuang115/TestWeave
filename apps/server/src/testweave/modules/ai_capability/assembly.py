from dataclasses import dataclass

from testweave.modules.ai_capability.config import ExternalAgentFeatureConfig


@dataclass(frozen=True)
class ExternalAgentModule:
    """不可变、无 I/O 的 External Agent 模块描述器。"""

    enabled: bool
    bind_host: str
    port: int


def setup_external_agent_module(config: ExternalAgentFeatureConfig) -> ExternalAgentModule | None:
    """按 ExternalAgentFeatureConfig 无副作用地组装 ExternalAgentModule。

    - enabled=False 时返回 None；
    - enabled=True 时仅构建纯内存模块描述器对象；
    - 绝不开启 socket 监听、Worker 线程、异步 Task 或注册任何 HTTP 路由。
    """
    if not config.enabled:
        return None

    return ExternalAgentModule(
        enabled=True,
        bind_host=config.bind_host,
        port=config.port,
    )
