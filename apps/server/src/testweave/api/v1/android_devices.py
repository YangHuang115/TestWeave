import asyncio
from datetime import UTC
from uuid import UUID, uuid4

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Path,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import Project
from testweave.modules.android_device_monitor.schemas import (
    AndroidDeviceListResponse,
    AndroidStreamError,
    AndroidStreamFrame,
)
from testweave.modules.android_device_monitor.service import AndroidDeviceMonitorService
from testweave.modules.android_device_monitor.stream import (
    AndroidDeviceStreamManager,
    AndroidDeviceStreamSubscription,
)
from testweave.shared.permissions import PROJECT_READ

router = APIRouter(prefix="/projects/{projectId}/android-devices", tags=["android-devices"])
project_read_permission = require_project_permission(PROJECT_READ)
logger = structlog.get_logger(__name__)


def get_android_device_monitor(request: Request) -> AndroidDeviceMonitorService:
    return request.app.state.android_device_monitor


def get_android_device_stream_manager(websocket: WebSocket) -> AndroidDeviceStreamManager:
    return websocket.app.state.android_device_stream_manager


async def websocket_origin_permission(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    allowed_origins = websocket.app.state.allowed_websocket_origins
    if origin is None or origin not in allowed_origins:
        raise WebSocketException(code=4403, reason="WebSocket 来源不受信任")


async def websocket_project_read_permission(
    websocket: WebSocket,
    projectId: UUID,
) -> None:
    websocket.state.request_id = websocket.headers.get("X-Request-ID") or str(uuid4())
    engine: Engine | None = websocket.app.state.database_engine
    if engine is None:
        raise RuntimeError("FastAPI state 中未初始化 database_engine")
    try:
        with Session(engine) as db:
            current_user = await get_current_user(websocket, db)
            await project_read_permission(websocket, projectId, db, current_user)
    except AppError as error:
        close_code = 4401 if error.status_code == 401 else 4403
        reason = (
            "登录状态已失效，请重新登录" if close_code == 4401 else "没有当前项目的设备查看权限"
        )
        raise WebSocketException(code=close_code, reason=reason) from error


@router.get("", response_model=AndroidDeviceListResponse)
async def list_android_devices(
    projectId: UUID = Path(...),
    _project: Project = Depends(project_read_permission),
    monitor: AndroidDeviceMonitorService = Depends(get_android_device_monitor),
) -> AndroidDeviceListResponse:
    """返回本机全部设备；projectId 仅用于复用项目成员权限校验。"""

    return await monitor.list_devices()


@router.get(
    "/{deviceRef}/screen",
    response_class=Response,
    responses={200: {"description": "PNG 设备当前画面", "content": {"image/png": {}}}},
)
async def get_android_device_screen(
    projectId: UUID = Path(...),
    deviceRef: str = Path(..., min_length=8, max_length=100),
    _project: Project = Depends(project_read_permission),
    monitor: AndroidDeviceMonitorService = Depends(get_android_device_monitor),
) -> Response:
    """按用户显式请求抓取一帧 PNG，不缓存也不落盘。"""

    screenshot = await monitor.screenshot(deviceRef)
    captured_at = screenshot.captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return Response(
        content=screenshot.content,
        media_type=screenshot.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Captured-At": captured_at,
        },
    )


def _stream_close_code(code: str) -> int:
    if code == "ANDROID_DEVICE_NOT_FOUND":
        return 4404
    if code == "ANDROID_DEVICE_UNAVAILABLE":
        return 4409
    return 4503


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def _cancel_task(task: asyncio.Task[object] | None) -> None:
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _send_stream_message(
    websocket: WebSocket,
    message: AndroidStreamFrame | AndroidStreamError,
) -> bool:
    if isinstance(message, AndroidStreamError):
        await websocket.send_json(
            {
                "type": "stream.error",
                "code": message.code,
                "message": message.message,
                "retryable": message.retryable,
            }
        )
        if message.terminal:
            await websocket.close(code=_stream_close_code(message.code))
            return False
        return True

    captured_at = message.captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    await websocket.send_json(
        {
            "type": "frame.meta",
            "sequence": message.sequence,
            "capturedAt": captured_at,
            "contentType": "image/png",
            "byteLength": len(message.content),
            "effectiveFps": message.effective_fps,
        }
    )
    await websocket.send_bytes(message.content)
    return True


@router.websocket("/{deviceRef}/stream")
async def stream_android_device_screen(
    websocket: WebSocket,
    projectId: UUID,
    deviceRef: str = Path(..., min_length=8, max_length=100),
    _origin: None = Depends(websocket_origin_permission),
    _project: None = Depends(websocket_project_read_permission),
    manager: AndroidDeviceStreamManager = Depends(get_android_device_stream_manager),
) -> None:
    """发送共享的只读 PNG 画面流，不接收设备控制消息。"""

    await websocket.accept()
    subscription: AndroidDeviceStreamSubscription | None = None
    disconnect_task: asyncio.Task[None] | None = None
    item_task: asyncio.Task[object] | None = None
    try:
        try:
            subscription = await manager.subscribe(deviceRef)
        except AppError as error:
            await websocket.close(code=_stream_close_code(error.code))
            return
        except Exception as error:
            logger.error(
                "android_stream_subscribe_failed",
                deviceRef=deviceRef,
                errorType=type(error).__name__,
            )
            await websocket.close(code=4503)
            return

        await websocket.send_json({"type": "stream.ready"})
        disconnect_task = asyncio.create_task(_wait_for_disconnect(websocket))
        while True:
            item_task = asyncio.create_task(subscription.get())
            done, _pending = await asyncio.wait(
                {item_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done:
                await _cancel_task(item_task)
                item_task = None
                return
            message = item_task.result()
            item_task = None
            if not await _send_stream_message(websocket, message):
                return
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        await _cancel_task(item_task)
        await _cancel_task(disconnect_task)
        if subscription is not None:
            await subscription.close()
