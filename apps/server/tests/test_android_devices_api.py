import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.v1 import android_devices
from testweave.core.errors import AppError
from testweave.main import create_app
from testweave.modules.android_device_monitor.schemas import (
    AndroidDeviceListResponse,
    AndroidScreenshot,
    AndroidStreamError,
    AndroidStreamFrame,
)
from testweave.modules.auth.service import AuthService

pytestmark = pytest.mark.anyio
WS_ORIGIN_HEADERS = {"origin": "http://localhost:5173"}


class FakeMonitor:
    def __init__(self) -> None:
        self.list_calls = 0
        self.screenshot_calls: list[str] = []

    async def list_devices(self) -> AndroidDeviceListResponse:
        self.list_calls += 1
        return AndroidDeviceListResponse(items=[], total=0)

    async def screenshot(self, device_ref: str) -> AndroidScreenshot:
        self.screenshot_calls.append(device_ref)
        return AndroidScreenshot(b"\x89PNG\r\n\x1a\nunit", datetime.now(UTC))


class FakeSubscription:
    def __init__(self, *messages: AndroidStreamFrame | AndroidStreamError) -> None:
        self.messages = list(messages)
        self.close_calls = 0
        self.wait_forever = asyncio.Event()

    async def get(self) -> AndroidStreamFrame | AndroidStreamError:
        if self.messages:
            return self.messages.pop(0)
        await self.wait_forever.wait()
        raise AssertionError("closed subscription must not return another message")

    async def close(self) -> None:
        self.close_calls += 1
        self.wait_forever.set()


class FakeStreamManager:
    def __init__(
        self,
        subscription: FakeSubscription | None = None,
        error: Exception | None = None,
        before_subscribe: Callable[[], None] | None = None,
    ) -> None:
        self.subscription = subscription
        self.error = error
        self.before_subscribe = before_subscribe
        self.subscribe_calls: list[str] = []

    async def subscribe(self, device_ref: str) -> FakeSubscription:
        self.subscribe_calls.append(device_ref)
        if self.before_subscribe is not None:
            self.before_subscribe()
        if self.error is not None:
            raise self.error
        assert self.subscription is not None
        return self.subscription


async def _allow_project() -> object:
    return object()


async def _allow_websocket_project() -> object:
    return object()


class ReadyProbe:
    def check(self) -> dict[str, str]:
        return {"database": "ok"}


def _app(
    monitor: FakeMonitor,
    *,
    allow_project: bool = True,
    stream_manager: FakeStreamManager | None = None,
):
    app = create_app(readiness_probe=ReadyProbe())
    app.state.android_device_monitor = monitor
    if stream_manager is not None:
        app.state.android_device_stream_manager = stream_manager
    if allow_project:
        app.dependency_overrides[android_devices.project_read_permission] = _allow_project
        app.dependency_overrides[android_devices.websocket_project_read_permission] = (
            _allow_websocket_project
        )
    return app


async def test_list_endpoint_is_read_only_and_uses_project_permission_dependency() -> None:
    monitor = FakeMonitor()
    app = _app(monitor)
    project_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project_id}/android-devices")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert monitor.list_calls == 1
    assert monitor.screenshot_calls == []


async def test_screen_endpoint_returns_png_without_cache() -> None:
    monitor = FakeMonitor()
    app = _app(monitor)
    project_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/screen"
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-captured-at"].endswith("Z")
    assert monitor.screenshot_calls == ["v1_test1"]


async def test_unauthenticated_request_returns_standard_401() -> None:
    monitor = FakeMonitor()
    app = _app(monitor, allow_project=False)
    app.dependency_overrides[get_db] = lambda: object()
    project_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project_id}/android-devices")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert monitor.list_calls == 0


async def test_non_member_request_returns_project_access_denied() -> None:
    monitor = FakeMonitor()
    app = _app(monitor, allow_project=False)
    project_id = uuid4()

    class FakeDb:
        def get(self, _model: object, _project_id: object) -> object:
            return SimpleNamespace(status="active")

        def scalar(self, _statement: object) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: FakeDb()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid4(), is_system_admin=False
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{project_id}/android-devices")

    assert response.status_code == 403
    assert response.json()["code"] == "PROJECT_ACCESS_DENIED"
    assert monitor.list_calls == 0


def test_stream_sends_ready_metadata_then_png_and_unsubscribes_on_disconnect() -> None:
    captured_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    subscription = FakeSubscription(
        AndroidStreamFrame(
            content=b"\x89PNG\r\n\x1a\nlive",
            captured_at=captured_at,
            sequence=42,
            effective_fps=1.1,
        )
    )
    manager = FakeStreamManager(subscription)
    app = _app(FakeMonitor(), stream_manager=manager)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ) as websocket,
    ):
        assert websocket.receive_json() == {"type": "stream.ready"}
        assert websocket.receive_json() == {
            "type": "frame.meta",
            "sequence": 42,
            "capturedAt": "2026-07-29T12:00:00Z",
            "contentType": "image/png",
            "byteLength": 12,
            "effectiveFps": 1.1,
        }
        assert websocket.receive_bytes() == b"\x89PNG\r\n\x1a\nlive"

    assert manager.subscribe_calls == ["v1_test1"]
    assert subscription.close_calls == 1


def test_stream_reports_transient_error_and_closes_on_terminal_device_error() -> None:
    subscription = FakeSubscription(
        AndroidStreamError(
            code="ANDROID_MCP_TIMEOUT",
            message="Android MCP 响应超时",
            retryable=True,
            terminal=False,
        ),
        AndroidStreamFrame(
            content=b"\x89PNG\r\n\x1a\nrecovered",
            captured_at=datetime(2026, 7, 29, 12, 0, 1, tzinfo=UTC),
            sequence=1,
            effective_fps=None,
        ),
        AndroidStreamError(
            code="ANDROID_DEVICE_UNAVAILABLE",
            message="设备当前离线或未授权",
            retryable=True,
            terminal=True,
        ),
    )
    manager = FakeStreamManager(subscription)
    app = _app(FakeMonitor(), stream_manager=manager)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ) as websocket,
    ):
        assert websocket.receive_json() == {"type": "stream.ready"}
        assert websocket.receive_json() == {
            "type": "stream.error",
            "code": "ANDROID_MCP_TIMEOUT",
            "message": "Android MCP 响应超时",
            "retryable": True,
        }
        assert websocket.receive_json()["type"] == "frame.meta"
        assert websocket.receive_bytes() == b"\x89PNG\r\n\x1a\nrecovered"
        assert websocket.receive_json()["code"] == "ANDROID_DEVICE_UNAVAILABLE"
        with pytest.raises(WebSocketDisconnect) as disconnect:
            websocket.receive_json()

    assert disconnect.value.code == 4409
    assert subscription.close_calls == 1


@pytest.mark.parametrize(
    ("error", "close_code"),
    [
        (
            AppError(
                code="ANDROID_STREAM_DISABLED",
                message="实时监看未启用",
                status_code=503,
                retryable=False,
            ),
            4503,
        ),
        (
            AppError(
                code="ANDROID_DEVICE_NOT_FOUND",
                message="设备不存在",
                status_code=404,
                retryable=True,
            ),
            4404,
        ),
        (
            AppError(
                code="ANDROID_DEVICE_UNAVAILABLE",
                message="设备离线",
                status_code=409,
                retryable=True,
            ),
            4409,
        ),
    ],
)
def test_stream_maps_subscription_failures_to_stable_close_codes(
    error: AppError,
    close_code: int,
) -> None:
    manager = FakeStreamManager(error=error)
    app = _app(FakeMonitor(), stream_manager=manager)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ) as websocket,
        pytest.raises(WebSocketDisconnect) as disconnect,
    ):
        websocket.receive_json()

    assert disconnect.value.code == close_code


def test_stream_hides_unexpected_subscription_failure_and_closes_with_4503() -> None:
    manager = FakeStreamManager(error=RuntimeError("unsafe vendor details"))
    app = _app(FakeMonitor(), stream_manager=manager)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ) as websocket,
        pytest.raises(WebSocketDisconnect) as disconnect,
    ):
        websocket.receive_json()

    assert disconnect.value.code == 4503


def test_stream_closes_unauthenticated_connection_with_4401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeStreamManager(FakeSubscription())
    app = _app(FakeMonitor(), allow_project=False, stream_manager=manager)

    class FakeDb:
        def __enter__(self) -> "FakeDb":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    app.state.database_engine = object()
    monkeypatch.setattr(android_devices, "Session", lambda _engine: FakeDb())
    project_id = uuid4()

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as disconnect,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ),
    ):
        pass

    assert disconnect.value.code == 4401
    assert disconnect.value.reason == "登录状态已失效，请重新登录"
    assert manager.subscribe_calls == []


def test_stream_closes_forbidden_connection_with_4403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeStreamManager(FakeSubscription())
    app = _app(FakeMonitor(), allow_project=False, stream_manager=manager)

    class FakeDb:
        def __enter__(self) -> "FakeDb":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _model: object, _project_id: object) -> object:
            return SimpleNamespace(status="active")

        def scalar(self, _statement: object) -> None:
            return None

    app.state.database_engine = object()
    monkeypatch.setattr(android_devices, "Session", lambda _engine: FakeDb())
    monkeypatch.setattr(
        AuthService,
        "get_user_by_session_token",
        lambda _db, _token: SimpleNamespace(id=uuid4(), is_system_admin=False),
    )
    project_id = uuid4()

    with TestClient(app) as client:
        client.cookies.set("session_token", "valid-session")
        with (
            pytest.raises(WebSocketDisconnect) as disconnect,
            client.websocket_connect(
                f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
                headers=WS_ORIGIN_HEADERS,
            ),
        ):
            pass

    assert disconnect.value.code == 4403
    assert disconnect.value.reason == "没有当前项目的设备查看权限"
    assert manager.subscribe_calls == []


@pytest.mark.parametrize("headers", [{}, {"origin": "http://localhost:9999"}])
def test_stream_rejects_missing_or_untrusted_origin_before_subscribing(
    headers: dict[str, str],
) -> None:
    manager = FakeStreamManager(FakeSubscription())
    app = _app(FakeMonitor(), stream_manager=manager)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as disconnect,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=headers,
        ),
    ):
        pass

    assert disconnect.value.code == 4403
    assert manager.subscribe_calls == []


def test_stream_closes_handshake_database_session_before_subscribing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_closed = False

    class FakeDb:
        def __enter__(self) -> "FakeDb":
            return self

        def __exit__(self, *_args: object) -> None:
            nonlocal session_closed
            session_closed = True

    def assert_session_closed() -> None:
        assert session_closed is True

    async def tracked_db_dependency():
        nonlocal session_closed
        try:
            yield FakeDb()
        finally:
            session_closed = True

    async def allow_current_user(_websocket: object, _db: object) -> object:
        return SimpleNamespace(id=uuid4(), is_system_admin=False)

    async def allow_project(
        _websocket: object,
        _project_id: object,
        _db: object,
        _current_user: object,
    ) -> object:
        return object()

    manager = FakeStreamManager(
        FakeSubscription(
            AndroidStreamError(
                code="ANDROID_DEVICE_UNAVAILABLE",
                message="设备当前离线或未授权",
                retryable=True,
                terminal=True,
            )
        ),
        before_subscribe=assert_session_closed,
    )
    app = _app(FakeMonitor(), allow_project=False, stream_manager=manager)
    app.state.database_engine = object()
    app.dependency_overrides[get_db] = tracked_db_dependency
    monkeypatch.setattr(android_devices, "Session", lambda _engine: FakeDb())
    monkeypatch.setattr(android_devices, "get_current_user", allow_current_user)
    monkeypatch.setattr(android_devices, "project_read_permission", allow_project)
    project_id = uuid4()

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/projects/{project_id}/android-devices/v1_test1/stream",
            headers=WS_ORIGIN_HEADERS,
        ) as websocket,
    ):
        assert websocket.receive_json() == {"type": "stream.ready"}

    assert session_closed is True
    assert manager.subscribe_calls == ["v1_test1"]
