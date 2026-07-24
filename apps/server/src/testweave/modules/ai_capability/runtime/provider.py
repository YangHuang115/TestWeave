import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

from testweave.core.errors import AppError
from testweave.modules.ai_capability.runtime.config import AIProviderSettings


class ProviderResponse(BaseModel):
    """ModelProvider 标准响应数据"""

    content_json: dict[str, Any]
    provider_name: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw_response_body: str | None = None


class ModelProvider(ABC):
    """ModelProvider 内部调用协议标准抽象接口"""

    @abstractmethod
    async def invoke_structured_json(
        self,
        instructions: str,
        input_data: dict[str, Any],
        output_schema: dict[str, Any],
        model_policy: str = "quality_first",
        timeout_seconds: int = 120,
        max_output_bytes: int = 2097152,
    ) -> ProviderResponse:
        """结构化 JSON 调用模型"""
        pass


class OpenAICompatibleProviderAdapter(ModelProvider):
    """OpenAI-Compatible 生产适配器 (基于 httpx JSON Schema Response Format)"""

    def __init__(self, settings: AIProviderSettings) -> None:
        self.settings = settings

    def _resolve_model(self, model_policy: str) -> str:
        # 模型策略逻辑别名映射
        if model_policy in {"quality_first", "quality"}:
            return self.settings.quality_model or "gpt-4o"
        return self.settings.quality_model or "gpt-4o"

    async def invoke_structured_json(
        self,
        instructions: str,
        input_data: dict[str, Any],
        output_schema: dict[str, Any],
        model_policy: str = "quality_first",
        timeout_seconds: int = 120,
        max_output_bytes: int = 2097152,
    ) -> ProviderResponse:
        if not self.settings.is_configured():
            raise AppError(
                code="RUN_PROVIDER_NOT_CONFIGURED",
                message="AI Provider 未在服务端正确配置 API Key 或 Base URL",
                status_code=500,
            )

        model_name = self._resolve_model(model_policy)
        base_url = self.settings.base_url.rstrip("/")
        endpoint = f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.settings.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        # 结构化 Prompt
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ]

        payload = {
            "model": model_name,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": output_schema,
                },
            },
            "temperature": 0.1,
        }

        actual_timeout = min(timeout_seconds, self.settings.timeout_seconds)

        try:
            async with httpx.AsyncClient(timeout=actual_timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)

                if response.status_code == 401 or response.status_code == 403:
                    raise AppError(
                        code="RUN_PROVIDER_AUTH_FAILED",
                        message=f"AI Provider 认证失败 HTTP {response.status_code}",
                        status_code=502,
                    )
                elif response.status_code == 429:
                    raise AppError(
                        code="RUN_PROVIDER_RATE_LIMITED",
                        message="AI Provider 触发频率限制 HTTP 429",
                        status_code=503,
                    )
                elif response.status_code >= 500:
                    raise AppError(
                        code="RUN_PROVIDER_UNAVAILABLE",
                        message=f"AI Provider 临时不可用 HTTP {response.status_code}",
                        status_code=502,
                    )
                elif response.status_code != 200:
                    raise AppError(
                        code="RUN_PROVIDER_RESPONSE_INVALID",
                        message=f"AI Provider 返回状态码 HTTP {response.status_code}",
                        status_code=502,
                    )

                if len(response.content) > max_output_bytes:
                    raise AppError(
                        code="RUN_OUTPUT_TOO_LARGE",
                        message=f"模型输出超过最大大小限制 {max_output_bytes} 字节",
                        status_code=400,
                    )

                body_data = response.json()
                choices = body_data.get("choices", [])
                if not choices:
                    raise AppError(
                        code="RUN_PROVIDER_RESPONSE_INVALID",
                        message="AI Provider 响应格式异常，缺少 choices",
                        status_code=502,
                    )

                msg_content = choices[0].get("message", {}).get("content", "")
                if not msg_content:
                    raise AppError(
                        code="RUN_PROVIDER_RESPONSE_INVALID",
                        message="AI Provider 返回内容为空",
                        status_code=502,
                    )

                try:
                    parsed_json = json.loads(msg_content)
                except Exception as e:
                    raise AppError(
                        code="RUN_PROVIDER_RESPONSE_INVALID",
                        message=f"模型响应并非合法 JSON: {e}",
                        status_code=502,
                    ) from e

                usage = body_data.get("usage", {})
                return ProviderResponse(
                    content_json=parsed_json,
                    provider_name="openai_compatible",
                    model_name=model_name,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                )

        except httpx.TimeoutException as terr:
            raise AppError(
                code="RUN_PROVIDER_TIMEOUT",
                message="AI Provider 请求超时",
                status_code=504,
            ) from terr
        except httpx.RequestError as req_err:
            raise AppError(
                code="RUN_PROVIDER_UNAVAILABLE",
                message=f"AI Provider 网络请求异常: {req_err}",
                status_code=502,
            ) from req_err


class FakeModelProvider(ModelProvider):
    """自动化测试专用的 Fake ModelProvider 替身"""

    def __init__(self, predefined_responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.predefined_responses = predefined_responses or {}

    async def invoke_structured_json(
        self,
        instructions: str,
        input_data: dict[str, Any],
        output_schema: dict[str, Any],
        model_policy: str = "quality_first",
        timeout_seconds: int = 120,
        max_output_bytes: int = 2097152,
    ) -> ProviderResponse:
        # 可根据指令关键词寻找预定义响应
        matched = None
        for key, resp in self.predefined_responses.items():
            if key in instructions or key in str(input_data):
                matched = resp
                break

        if not matched:
            # 默认 Fake 输出
            matched = {"status": "success", "result": "fake_generated_output"}

        return ProviderResponse(
            content_json=matched,
            provider_name="fake_provider",
            model_name="fake-model-v1",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
