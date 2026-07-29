import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import anyio
import mcp
import mcp.client.stdio as mcp_stdio
import pytest

from testweave.core.errors import AppError
from testweave.infrastructure.android_mcp.client import (
    _DISCARDING_ERRLOG,
    ReadOnlyAndroidMcpClient,
)
from testweave.modules.android_device_monitor.config import AndroidMcpSettings


class FakeSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def call_tool(self, name: str, arguments: dict[str, str]) -> object:
        self.calls.append((name, arguments))
        return self.result


def _client(session: FakeSession) -> ReadOnlyAndroidMcpClient:
    return ReadOnlyAndroidMcpClient(AndroidMcpSettings(enabled=True), session=session)


def test_read_only_client_never_forwards_save_path() -> None:
    session = FakeSession(SimpleNamespace(content=[]))
    client = _client(session)

    with pytest.raises(AppError) as error:
        asyncio.run(client.screenshot("emulator-5554"))

    assert error.value.code == "ANDROID_MCP_PROTOCOL_ERROR"
    assert session.calls == [("screenshot", {"device_id": "emulator-5554"})]
    assert all("save_path" not in args for _, args in session.calls)


def test_read_only_client_rejects_arbitrary_tool_names() -> None:
    session = FakeSession(SimpleNamespace(content=[]))
    client = _client(session)

    with pytest.raises(AppError) as error:
        asyncio.run(client._invoke("tap", {"device_id": "emulator-5554"}))

    assert error.value.code == "ANDROID_MCP_PROTOCOL_ERROR"
    assert session.calls == []


def test_validate_tools_requires_device_id_for_info_and_screenshot() -> None:
    tools = [
        {"name": "list_devices", "inputSchema": {"properties": {}}},
        {"name": "get_device_info", "inputSchema": {"properties": {}}},
        {"name": "screenshot", "inputSchema": {"properties": {"device_id": {}}}},
    ]

    with pytest.raises(AppError) as error:
        ReadOnlyAndroidMcpClient._validate_tools({"tools": tools})

    assert error.value.code == "ANDROID_MCP_PROTOCOL_ERROR"


def test_disabled_runtime_does_not_spawn_or_call_session() -> None:
    client = ReadOnlyAndroidMcpClient(AndroidMcpSettings(enabled=False))

    with pytest.raises(AppError) as error:
        asyncio.run(client.list_devices())

    assert error.value.code == "ANDROID_MCP_DISABLED"


def test_stdio_stderr_sink_is_compatible_with_anyio_process() -> None:
    async def spawn_process() -> None:
        process = await anyio.open_process(["/usr/bin/true"], stderr=_DISCARDING_ERRLOG)
        await process.wait()

    asyncio.run(spawn_process())


def test_session_tool_calls_are_serialized() -> None:
    class ConcurrentSession(FakeSession):
        def __init__(self) -> None:
            super().__init__(SimpleNamespace(content=[]))
            self.active_calls = 0
            self.max_active_calls = 0

        async def call_tool(self, name: str, arguments: dict[str, str]) -> object:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            return await super().call_tool(name, arguments)

    async def scenario() -> int:
        session = ConcurrentSession()
        client = _client(session)
        await asyncio.gather(
            client._invoke("list_devices", {}),
            client._invoke("list_devices", {}),
        )
        return session.max_active_calls

    assert asyncio.run(scenario()) == 1


def test_cancelled_tool_call_invalidates_session_before_reuse() -> None:
    class BlockingSession(FakeSession):
        def __init__(self) -> None:
            super().__init__(SimpleNamespace(content=[]))
            self.started = asyncio.Event()

        async def call_tool(self, name: str, arguments: dict[str, str]) -> object:
            self.started.set()
            await asyncio.Event().wait()
            return await super().call_tool(name, arguments)

    async def scenario() -> object:
        session = BlockingSession()
        client = _client(session)
        call = asyncio.create_task(client._invoke("list_devices", {}))
        await session.started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        return client._session

    assert asyncio.run(scenario()) is None


def test_cancelled_node_version_check_terminates_probe_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingProcess:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.killed = False
            self.waited = False
            self.returncode: int | None = None

        async def communicate(self) -> tuple[bytes, bytes]:
            self.started.set()
            await asyncio.Event().wait()
            return b"v24.0.0", b""

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            self.waited = True
            return self.returncode or 0

    process = BlockingProcess()

    async def create_process(*_args: object, **_kwargs: object) -> BlockingProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    async def scenario() -> None:
        client = ReadOnlyAndroidMcpClient(AndroidMcpSettings(enabled=True))
        check = asyncio.create_task(
            client._validate_node_runtime(
                Path("/usr/bin/node"),
                Path("/tmp"),
            )
        )
        await process.started.wait()
        check.cancel()
        with pytest.raises(asyncio.CancelledError):
            await check

    asyncio.run(scenario())

    assert process.killed is True
    assert process.waited is True


def test_cancelled_lazy_start_closes_partially_opened_stdio_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = SimpleNamespace(
        initialize_started=None,
        stdio_closed=False,
        session_closed=False,
    )

    @asynccontextmanager
    async def fake_stdio(
        *_args: object,
        **_kwargs: object,
    ) -> AsyncIterator[tuple[object, object]]:
        try:
            yield object(), object()
        finally:
            state.stdio_closed = True

    class BlockingClientSession:
        def __init__(self, *_args: object) -> None:
            self.initialize_started = asyncio.Event()
            state.initialize_started = self.initialize_started

        async def __aenter__(self) -> "BlockingClientSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            state.session_closed = True

        async def initialize(self) -> None:
            self.initialize_started.set()
            await asyncio.Event().wait()

    node_path = tmp_path / "node"
    entrypoint = tmp_path / "android-mcp.mjs"
    node_path.touch()
    entrypoint.touch()
    monkeypatch.setattr(mcp_stdio, "stdio_client", fake_stdio)
    monkeypatch.setattr(mcp, "ClientSession", BlockingClientSession)

    async def scenario() -> tuple[object, object]:
        client = ReadOnlyAndroidMcpClient(
            AndroidMcpSettings(
                enabled=True,
                node_path=str(node_path),
                entrypoint=str(entrypoint),
                cwd=str(tmp_path),
            )
        )

        async def skip_runtime_check(*_args: object) -> None:
            return None

        monkeypatch.setattr(client, "_validate_node_runtime", skip_runtime_check)
        call = asyncio.create_task(client._invoke("list_devices", {}))
        while state.initialize_started is None:
            await asyncio.sleep(0)
        await state.initialize_started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        return client._session, client._stack

    session, stack = asyncio.run(scenario())

    assert session is None
    assert stack is None
    assert state.session_closed is True
    assert state.stdio_closed is True
