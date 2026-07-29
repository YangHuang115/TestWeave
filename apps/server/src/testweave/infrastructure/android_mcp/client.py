import asyncio
import os
import re
import subprocess
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, TextIO, cast

import structlog

from testweave.core.errors import AppError
from testweave.modules.android_device_monitor.config import AndroidMcpSettings
from testweave.modules.android_device_monitor.parser import (
    AndroidMcpProtocolError,
    parse_device_info,
    parse_device_list,
    parse_screenshot,
)

READ_ONLY_TOOL_NAMES = frozenset({"list_devices", "get_device_info", "screenshot"})


# AnyIO passes this value directly to subprocess.Popen. DEVNULL is a real,
# inheritable file descriptor and prevents vendor/ADB stderr from entering
# application logs or API responses.
_DISCARDING_ERRLOG = subprocess.DEVNULL
_REQUIRED_NODE_MAJOR = 24
logger = structlog.get_logger(__name__)


class ReadOnlyAndroidMcpClient:
    """Long-lived, code-level allowlist over the vendor MCP session."""

    def __init__(
        self,
        settings: AndroidMcpSettings,
        *,
        session: Any | None = None,
    ) -> None:
        self.settings = settings
        self._session = session
        self._stack: AsyncExitStack | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._call_lock, self._lifecycle_lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        self._session = None
        if self._stack is not None:
            stack, self._stack = self._stack, None
            await stack.aclose()

    def _configuration_error(self) -> AppError | None:
        if not self.settings.enabled:
            return AppError(
                code="ANDROID_MCP_DISABLED",
                message="Android MCP 未启用，请先配置本机独立运行时",
                status_code=503,
                retryable=False,
            )
        if not self.settings.node_path or not self.settings.entrypoint or not self.settings.cwd:
            return AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="Android MCP 运行时配置不完整",
                status_code=503,
                retryable=True,
            )
        return None

    def _build_env(self) -> dict[str, str]:
        allowed = {
            "HOME",
            "PATH",
            "ANDROID_HOME",
            "ANDROID_SDK_ROOT",
            "TMPDIR",
            "LANG",
            "LC_ALL",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.setdefault("LC_ALL", "C")
        return env

    async def _validate_node_runtime(self, node_path: Path, cwd: Path) -> None:
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(node_path),
                "--version",
                cwd=str(cwd),
                env=self._build_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=min(self.settings.timeout_seconds, 5)
            )
        except asyncio.CancelledError:
            if process is not None:
                try:
                    if process.returncode is None:
                        process.kill()
                    await asyncio.shield(process.wait())
                except Exception as cleanup_error:
                    logger.error(
                        "android_mcp_node_probe_cleanup_failed",
                        errorType=type(cleanup_error).__name__,
                    )
            raise
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise AppError(
                code="ANDROID_MCP_TIMEOUT",
                message="检查 Android MCP Node 运行时版本超时",
                status_code=504,
                retryable=True,
            ) from exc
        except OSError as exc:
            raise AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="无法执行 Android MCP Node 运行时",
                status_code=503,
                retryable=True,
            ) from exc

        version = stdout.decode("utf-8", errors="replace").strip()
        match = re.fullmatch(r"v(\d+)(?:\.\d+){0,2}", version)
        if process.returncode != 0 or match is None or int(match.group(1)) != _REQUIRED_NODE_MAJOR:
            raise AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="Android MCP 必须使用 Node 24 运行时",
                status_code=503,
                retryable=False,
            )

    async def _start_unlocked(self) -> Any:
        error = self._configuration_error()
        if error:
            raise error
        assert self.settings.node_path and self.settings.entrypoint and self.settings.cwd
        node_path = Path(self.settings.node_path).expanduser()
        entrypoint = Path(self.settings.entrypoint).expanduser()
        cwd = Path(self.settings.cwd).expanduser()
        if (
            not node_path.is_absolute()
            or not entrypoint.is_absolute()
            or not cwd.is_absolute()
            or not node_path.is_file()
            or not entrypoint.is_file()
            or not cwd.is_dir()
        ):
            raise AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="Android MCP 运行时路径不存在",
                status_code=503,
                retryable=True,
            )

        await self._validate_node_runtime(node_path, cwd)

        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
        except ImportError as exc:
            raise AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="服务端缺少 Python MCP 客户端依赖",
                status_code=503,
                retryable=False,
            ) from exc

        stack = AsyncExitStack()
        try:
            parameters = StdioServerParameters(
                command=str(node_path),
                args=[str(entrypoint)],
                env=self._build_env(),
                cwd=str(cwd),
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(parameters, errlog=cast(TextIO, _DISCARDING_ERRLOG))
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await asyncio.wait_for(session.initialize(), timeout=self.settings.timeout_seconds)
            listed = await asyncio.wait_for(
                session.list_tools(), timeout=self.settings.timeout_seconds
            )
            self._validate_tools(listed)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(stack.aclose())
            except Exception as cleanup_error:
                logger.error(
                    "android_mcp_startup_cleanup_failed",
                    errorType=type(cleanup_error).__name__,
                )
            raise
        except TimeoutError as exc:
            await stack.aclose()
            raise AppError(
                code="ANDROID_MCP_TIMEOUT",
                message="Android MCP 响应超时",
                status_code=504,
                retryable=True,
            ) from exc
        except AppError:
            await stack.aclose()
            raise
        except Exception as exc:
            await stack.aclose()
            raise AppError(
                code="ANDROID_MCP_UNAVAILABLE",
                message="无法启动 Android MCP 运行时",
                status_code=503,
                retryable=True,
            ) from exc
        self._stack = stack
        self._session = session
        return session

    @staticmethod
    def _validate_tools(tool_result: Any) -> None:
        tools = getattr(tool_result, "tools", None)
        if tools is None and isinstance(tool_result, dict):
            tools = tool_result.get("tools")
        tools = tools or []
        by_name: dict[str, Any] = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None and isinstance(tool, dict):
                name = tool.get("name")
            if name:
                by_name[name] = tool
        missing = READ_ONLY_TOOL_NAMES.difference(by_name)
        if missing:
            raise AppError(
                code="ANDROID_MCP_PROTOCOL_ERROR",
                message="Android MCP 缺少必需的只读工具",
                status_code=502,
                retryable=True,
                details={"missingTools": sorted(missing)},
            )
        for name in ("get_device_info", "screenshot"):
            tool = by_name[name]
            schema = getattr(tool, "inputSchema", None)
            if schema is None and isinstance(tool, dict):
                schema = tool.get("inputSchema") or tool.get("input_schema")
            properties = (schema or {}).get("properties", {})
            if "device_id" not in properties:
                raise AppError(
                    code="ANDROID_MCP_PROTOCOL_ERROR",
                    message="Android MCP 只读工具输入结构不兼容",
                    status_code=502,
                    retryable=True,
                )

    async def _session_or_start(self) -> Any:
        if self._session is not None:
            return self._session
        async with self._lifecycle_lock:
            if self._session is None:
                return await self._start_unlocked()
            return self._session

    async def _invoke(self, name: str, arguments: dict[str, str]) -> Any:
        if name not in READ_ONLY_TOOL_NAMES:
            raise AppError(
                code="ANDROID_MCP_PROTOCOL_ERROR",
                message="Android MCP 工具不在只读白名单内",
                status_code=502,
                retryable=False,
            )
        async with self._call_lock:
            try:
                session = await self._session_or_start()
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments), timeout=self.settings.timeout_seconds
                )
            except asyncio.CancelledError:
                async with self._lifecycle_lock:
                    await self._close_unlocked()
                raise
            except TimeoutError as exc:
                async with self._lifecycle_lock:
                    await self._close_unlocked()
                raise AppError(
                    code="ANDROID_MCP_TIMEOUT",
                    message="Android MCP 响应超时",
                    status_code=504,
                    retryable=True,
                ) from exc
            except AppError:
                raise
            except Exception as exc:
                async with self._lifecycle_lock:
                    await self._close_unlocked()
                raise AppError(
                    code="ANDROID_MCP_UNAVAILABLE",
                    message="Android MCP 运行时连接已断开",
                    status_code=503,
                    retryable=True,
                ) from exc
            if getattr(result, "isError", False) or (
                isinstance(result, dict) and result.get("isError")
            ):
                async with self._lifecycle_lock:
                    await self._close_unlocked()
                raise AppError(
                    code="ANDROID_MCP_PROTOCOL_ERROR",
                    message="Android MCP 返回工具错误",
                    status_code=502,
                    retryable=True,
                )
            return result

    @staticmethod
    def _content(result: Any) -> list[Any]:
        content = getattr(result, "content", None)
        if content is None and isinstance(result, dict):
            content = result.get("content")
        return list(content or [])

    @classmethod
    def _text(cls, result: Any) -> str:
        chunks: list[str] = []
        for block in cls._content(result):
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
            else:
                continue
            if text:
                chunks.append(str(text))
        return "\n".join(chunks)

    async def list_devices(self):
        try:
            return parse_device_list(self._text(await self._invoke("list_devices", {})))
        except AndroidMcpProtocolError as exc:
            await self.close()
            raise AppError(
                code="ANDROID_MCP_PROTOCOL_ERROR",
                message="Android MCP 设备列表响应无法解析",
                status_code=502,
                retryable=True,
            ) from exc

    async def get_device_info(self, device_id: str):
        try:
            result = await self._invoke("get_device_info", {"device_id": device_id})
            return parse_device_info(self._text(result))
        except AndroidMcpProtocolError as exc:
            await self.close()
            raise AppError(
                code="ANDROID_MCP_PROTOCOL_ERROR",
                message="Android MCP 设备信息响应无法解析",
                status_code=502,
                retryable=True,
            ) from exc

    async def screenshot(self, device_id: str) -> bytes:
        try:
            result = await self._invoke("screenshot", {"device_id": device_id})
            return parse_screenshot(
                self._content(result), max_bytes=self.settings.max_screenshot_bytes
            )
        except AndroidMcpProtocolError as exc:
            await self.close()
            raise AppError(
                code="ANDROID_MCP_PROTOCOL_ERROR",
                message="Android MCP 截图响应无法解析",
                status_code=502,
                retryable=True,
            ) from exc
