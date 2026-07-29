import asyncio
import base64
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from testweave.core.errors import AppError
from testweave.modules.android_device_monitor.parser import ParsedDevice
from testweave.modules.android_device_monitor.schemas import (
    AndroidDeviceItem,
    AndroidDeviceListResponse,
    AndroidScreenshot,
)


class AndroidMcpAdapter(Protocol):
    async def list_devices(self) -> list[ParsedDevice]: ...

    async def get_device_info(self, device_id: str) -> dict[str, str]: ...

    async def screenshot(self, device_id: str) -> bytes: ...


@dataclass(frozen=True)
class _ResolvedDevice:
    ref: str
    device: ParsedDevice


@dataclass(frozen=True)
class AndroidStreamDevice:
    device_ref: str
    device_id: str = field(repr=False)


@dataclass
class _DeviceLockEntry:
    lock: asyncio.Lock
    users: int = 0


class AndroidDeviceMonitorService:
    def __init__(
        self,
        adapter: AndroidMcpAdapter,
        *,
        secret: str,
        max_info_concurrency: int = 4,
        audit: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._secret = secret.encode("utf-8")
        self._max_info_concurrency = max_info_concurrency
        self._locks: dict[str, _DeviceLockEntry] = {}
        self._locks_guard = asyncio.Lock()
        self._audit = audit

    def device_ref(self, device_id: str) -> str:
        digest = hmac.new(self._secret, device_id.encode("utf-8"), hashlib.sha256).digest()
        return "v1_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _mask_device_id(device_id: str) -> str:
        if len(device_id) <= 8:
            return "设备 " + device_id[:2] + "…" + device_id[-2:]
        return "设备 " + device_id[:4] + "…" + device_id[-4:]

    async def _info_for(
        self, device: ParsedDevice, semaphore: asyncio.Semaphore
    ) -> dict[str, str] | None:
        async with semaphore:
            return await self._adapter.get_device_info(device.device_id)

    async def list_devices(self) -> AndroidDeviceListResponse:
        devices = await self._adapter.list_devices()
        semaphore = asyncio.Semaphore(self._max_info_concurrency)

        async def build_item(device: ParsedDevice) -> AndroidDeviceItem:
            info: dict[str, str] | None = None
            info_error: str | None = None
            if device.state == "online":
                try:
                    info = await self._info_for(device, semaphore)
                except Exception:
                    info_error = "设备信息暂不可用"
            else:
                info_error = "设备当前不可用"
            model = (info or {}).get("model") or device.model
            return AndroidDeviceItem(
                device_ref=self.device_ref(device.device_id),
                display_name=model or self._mask_device_id(device.device_id),
                state=device.state,
                model=model,
                info_available=info is not None,
                info_error=info_error,
            )

        items = list(await asyncio.gather(*(build_item(device) for device in devices)))
        return AndroidDeviceListResponse(items=items, total=len(items))

    async def _resolve(self, device_ref: str) -> _ResolvedDevice:
        if not re.fullmatch(r"v1_[A-Za-z0-9_-]{43}", device_ref):
            raise AppError(
                code="ANDROID_DEVICE_NOT_FOUND",
                message="设备不存在或已从本机设备列表移除",
                status_code=404,
                retryable=True,
            )
        devices = await self._adapter.list_devices()
        for device in devices:
            if hmac.compare_digest(self.device_ref(device.device_id), device_ref):
                return _ResolvedDevice(ref=device_ref, device=device)
        raise AppError(
            code="ANDROID_DEVICE_NOT_FOUND",
            message="设备不存在或已从本机设备列表移除",
            status_code=404,
            retryable=True,
        )

    async def _acquire_device_lock(self, device_ref: str) -> _DeviceLockEntry:
        async with self._locks_guard:
            entry = self._locks.get(device_ref)
            if entry is None:
                entry = _DeviceLockEntry(asyncio.Lock())
                self._locks[device_ref] = entry
            entry.users += 1
            return entry

    async def _release_device_lock(self, device_ref: str, entry: _DeviceLockEntry) -> None:
        async with self._locks_guard:
            entry.users -= 1
            if entry.users == 0 and self._locks.get(device_ref) is entry:
                self._locks.pop(device_ref, None)

    @staticmethod
    def _require_online(resolved: _ResolvedDevice) -> None:
        if resolved.device.state != "online":
            raise AppError(
                code="ANDROID_DEVICE_UNAVAILABLE",
                message="设备当前离线或未授权，无法抓取画面",
                status_code=409,
                retryable=True,
            )

    async def open_stream_device(self, device_ref: str) -> AndroidStreamDevice:
        resolved = await self._resolve(device_ref)
        self._require_online(resolved)
        return AndroidStreamDevice(
            device_ref=device_ref,
            device_id=resolved.device.device_id,
        )

    async def revalidate_stream_device(self, stream_device: AndroidStreamDevice) -> None:
        resolved = await self._resolve(stream_device.device_ref)
        self._require_online(resolved)
        if not hmac.compare_digest(resolved.device.device_id, stream_device.device_id):
            raise AppError(
                code="ANDROID_DEVICE_NOT_FOUND",
                message="设备不存在或已从本机设备列表移除",
                status_code=404,
                retryable=True,
            )

    async def capture_stream_frame(
        self,
        stream_device: AndroidStreamDevice,
        *,
        recheck: bool,
    ) -> AndroidScreenshot:
        entry = await self._acquire_device_lock(stream_device.device_ref)
        try:
            async with entry.lock:
                if recheck:
                    await self.revalidate_stream_device(stream_device)
                content = await self._adapter.screenshot(stream_device.device_id)
                captured_at = datetime.now(UTC)
                if self._audit:
                    await self._audit(stream_device.device_ref)
                return AndroidScreenshot(content, captured_at)
        finally:
            await self._release_device_lock(stream_device.device_ref, entry)

    async def screenshot(self, device_ref: str) -> AndroidScreenshot:
        # Resolve before creating a per-device lock so arbitrary unknown refs
        # cannot grow an unbounded lock table. Revalidation after acquiring the
        # shared lock preserves the existing single-frame freshness guarantee.
        stream_device = await self.open_stream_device(device_ref)
        return await self.capture_stream_frame(stream_device, recheck=True)
