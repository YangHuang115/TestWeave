import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from testweave.core.errors import AppError
from testweave.modules.android_device_monitor.schemas import (
    AndroidStreamError,
    AndroidStreamFrame,
)
from testweave.modules.android_device_monitor.service import AndroidStreamDevice
from testweave.modules.android_device_monitor.stream import AndroidDeviceStreamManager

pytestmark = pytest.mark.anyio


class ControlledMonitor:
    def __init__(self) -> None:
        self.capture_results: asyncio.Queue[object] = asyncio.Queue()
        self.open_calls = 0
        self.capture_calls = 0
        self.revalidate_calls = 0
        self.capture_cancelled = False
        self.revalidate_error: Exception | None = None
        self.open_error: Exception | None = None

    async def open_stream_device(self, device_ref: str) -> AndroidStreamDevice:
        self.open_calls += 1
        if self.open_error is not None:
            raise self.open_error
        return AndroidStreamDevice(device_ref=device_ref, device_id="physical-device")

    async def capture_stream_frame(
        self,
        _device: AndroidStreamDevice,
        *,
        recheck: bool,
    ):
        self.capture_calls += 1
        if recheck:
            self.revalidate_calls += 1
        try:
            result = await self.capture_results.get()
        except asyncio.CancelledError:
            self.capture_cancelled = True
            raise
        if isinstance(result, Exception):
            raise result
        return result

    async def revalidate_stream_device(self, _device: AndroidStreamDevice) -> None:
        self.revalidate_calls += 1
        if self.revalidate_error is not None:
            raise self.revalidate_error


async def wait_until(predicate, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def screenshot(content: bytes) -> object:
    from testweave.modules.android_device_monitor.schemas import AndroidScreenshot

    return AndroidScreenshot(content, datetime.now(UTC))


async def test_disabled_stream_rejects_subscription_without_resolving_device() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=False,
        interval_seconds=0.5,
        idle_grace_seconds=3,
        device_recheck_seconds=5,
        max_backoff_seconds=5,
    )

    with pytest.raises(AppError) as error:
        await manager.subscribe("v1_device")

    assert error.value.code == "ANDROID_STREAM_DISABLED"
    assert monitor.open_calls == 0
    assert manager.active_producer_count == 0
    await manager.shutdown()


async def test_subscribers_share_one_producer_and_drop_stale_frames() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )

    first = await manager.subscribe("v1_device")
    second = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    for index in range(1, 4):
        await monitor.capture_results.put(screenshot(f"frame-{index}".encode()))
        await wait_until(lambda expected=index + 1: monitor.capture_calls == expected)

    first_frame = cast(AndroidStreamFrame, await first.get())
    second_frame = cast(AndroidStreamFrame, await second.get())

    assert manager.active_producer_count == 1
    assert monitor.open_calls == 1
    assert first_frame.sequence == 3
    assert first_frame.content == b"frame-3"
    assert second_frame.sequence == 3
    assert second_frame.content == b"frame-3"

    await first.close()
    await second.close()
    await manager.shutdown()


async def test_active_producer_periodically_rechecks_device_state() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0.01,
        idle_grace_seconds=0,
        device_recheck_seconds=0.001,
        max_backoff_seconds=0.01,
    )
    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await monitor.capture_results.put(screenshot(b"first"))
    await wait_until(lambda: monitor.capture_calls == 2)

    assert monitor.revalidate_calls == 1
    await subscription.close()
    await manager.shutdown()


async def test_last_subscriber_stops_producer_after_idle_grace() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0.01,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )

    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)
    await subscription.close()
    await wait_until(lambda: manager.active_producer_count == 0)
    await wait_until(lambda: monitor.capture_cancelled)

    assert monitor.capture_cancelled is True
    await manager.shutdown()


async def test_transient_failure_is_reported_then_stream_recovers() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await monitor.capture_results.put(
        AppError(
            code="ANDROID_MCP_TIMEOUT",
            message="Android MCP 响应超时",
            status_code=504,
            retryable=True,
        )
    )
    error = cast(AndroidStreamError, await subscription.get())

    assert error.code == "ANDROID_MCP_TIMEOUT"
    assert error.retryable is True
    assert error.terminal is False
    assert monitor.revalidate_calls == 1

    await monitor.capture_results.put(screenshot(b"recovered"))
    frame = cast(AndroidStreamFrame, await subscription.get())

    assert frame.content == b"recovered"
    await subscription.close()
    await manager.shutdown()


async def test_device_unavailable_after_capture_failure_terminates_producer() -> None:
    monitor = ControlledMonitor()
    monitor.revalidate_error = AppError(
        code="ANDROID_DEVICE_UNAVAILABLE",
        message="设备当前离线或未授权",
        status_code=409,
        retryable=True,
    )
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await monitor.capture_results.put(
        AppError(
            code="ANDROID_MCP_UNAVAILABLE",
            message="Android MCP 运行时连接已断开",
            status_code=503,
            retryable=True,
        )
    )
    error = cast(AndroidStreamError, await subscription.get())
    await wait_until(lambda: manager.active_producer_count == 0)

    assert error.code == "ANDROID_DEVICE_UNAVAILABLE"
    assert error.terminal is True
    await subscription.close()
    await manager.shutdown()


async def test_unexpected_capture_failure_is_terminal_instead_of_retrying_forever() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await monitor.capture_results.put(RuntimeError("vendor failure with unsafe details"))
    error = cast(AndroidStreamError, await subscription.get())
    await wait_until(lambda: manager.active_producer_count == 0)

    assert error.code == "ANDROID_STREAM_ERROR"
    assert error.message == "实时画面暂时不可用"
    assert error.terminal is True
    assert monitor.capture_calls == 1
    await subscription.close()
    await manager.shutdown()


async def test_unexpected_revalidation_failure_notifies_subscriber_before_stopping() -> None:
    monitor = ControlledMonitor()
    monitor.revalidate_error = RuntimeError("unsafe vendor details")
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    subscription = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await monitor.capture_results.put(
        AppError(
            code="ANDROID_MCP_TIMEOUT",
            message="Android MCP 响应超时",
            status_code=504,
            retryable=True,
        )
    )
    async with asyncio.timeout(1):
        error = cast(AndroidStreamError, await subscription.get())
    await wait_until(lambda: manager.active_producer_count == 0)

    assert error.code == "ANDROID_STREAM_ERROR"
    assert error.message == "实时画面暂时不可用"
    assert error.terminal is True
    await subscription.close()
    await manager.shutdown()


async def test_terminal_producer_cannot_accept_subscriber_after_final_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = ControlledMonitor()
    monitor.revalidate_error = AppError(
        code="ANDROID_DEVICE_UNAVAILABLE",
        message="设备当前离线或未授权",
        status_code=409,
        retryable=True,
    )
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    producer_finished = asyncio.Event()
    allow_finish = asyncio.Event()
    original_finished = manager._producer_finished

    async def delayed_finish(producer: object) -> None:
        producer_finished.set()
        await allow_finish.wait()
        await original_finished(producer)  # type: ignore[arg-type]

    monkeypatch.setattr(manager, "_producer_finished", delayed_finish)
    first = await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    terminal_open_error = AppError(
        code="ANDROID_DEVICE_UNAVAILABLE",
        message="设备当前离线或未授权",
        status_code=409,
        retryable=True,
    )
    monitor.open_error = terminal_open_error
    await monitor.capture_results.put(
        AppError(
            code="ANDROID_MCP_UNAVAILABLE",
            message="Android MCP 运行时连接已断开",
            status_code=503,
            retryable=True,
        )
    )
    message = cast(AndroidStreamError, await first.get())
    await producer_finished.wait()

    try:
        with pytest.raises(AppError) as error:
            await manager.subscribe("v1_device")
    finally:
        allow_finish.set()

    assert message.code == "ANDROID_DEVICE_UNAVAILABLE"
    assert error.value.code == "ANDROID_DEVICE_UNAVAILABLE"
    assert monitor.open_calls == 2
    await first.close()
    await manager.shutdown()


async def test_shutdown_cancels_active_producers_without_leaking_tasks() -> None:
    monitor = ControlledMonitor()
    manager = AndroidDeviceStreamManager(
        monitor,
        enabled=True,
        interval_seconds=0,
        idle_grace_seconds=0,
        device_recheck_seconds=60,
        max_backoff_seconds=0.01,
    )
    await manager.subscribe("v1_device")
    await wait_until(lambda: monitor.capture_calls == 1)

    await manager.shutdown()

    assert manager.active_producer_count == 0
    assert monitor.capture_cancelled is True
