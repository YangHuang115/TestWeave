import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from testweave.core.errors import AppError
from testweave.modules.android_device_monitor.schemas import (
    AndroidScreenshot,
    AndroidStreamError,
    AndroidStreamFrame,
    AndroidStreamMessage,
)
from testweave.modules.android_device_monitor.service import AndroidStreamDevice

_TERMINAL_DEVICE_CODES = frozenset(
    {
        "ANDROID_DEVICE_NOT_FOUND",
        "ANDROID_DEVICE_UNAVAILABLE",
    }
)
logger = structlog.get_logger(__name__)


class AndroidStreamMonitor(Protocol):
    async def open_stream_device(self, device_ref: str) -> AndroidStreamDevice: ...

    async def capture_stream_frame(
        self,
        stream_device: AndroidStreamDevice,
        *,
        recheck: bool,
    ) -> AndroidScreenshot: ...

    async def revalidate_stream_device(self, stream_device: AndroidStreamDevice) -> None: ...


@dataclass(eq=False)
class _Producer:
    device_ref: str
    stream_device: AndroidStreamDevice
    subscribers: set[asyncio.Queue[AndroidStreamMessage]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    idle_task: asyncio.Task[None] | None = None
    sequence: int = 0


class AndroidDeviceStreamSubscription:
    def __init__(
        self,
        manager: "AndroidDeviceStreamManager",
        device_ref: str,
        queue: asyncio.Queue[AndroidStreamMessage],
    ) -> None:
        self._manager = manager
        self._device_ref = device_ref
        self._queue = queue
        self._closed = False

    async def get(self) -> AndroidStreamMessage:
        return await self._queue.get()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._manager._unsubscribe(self._device_ref, self._queue)


class AndroidDeviceStreamManager:
    def __init__(
        self,
        monitor: AndroidStreamMonitor,
        *,
        enabled: bool,
        interval_seconds: float,
        idle_grace_seconds: float,
        device_recheck_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        self._monitor = monitor
        self._enabled = enabled
        self._interval_seconds = interval_seconds
        self._idle_grace_seconds = idle_grace_seconds
        self._device_recheck_seconds = device_recheck_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._guard = asyncio.Lock()
        self._producers: dict[str, _Producer] = {}
        self._closed = False

    @property
    def active_producer_count(self) -> int:
        return len(self._producers)

    async def subscribe(self, device_ref: str) -> AndroidDeviceStreamSubscription:
        if not self._enabled:
            raise AppError(
                code="ANDROID_STREAM_DISABLED",
                message="实时监看未启用，当前仍可获取单帧",
                status_code=503,
                retryable=False,
            )

        subscription, idle_task = await self._subscribe_existing(device_ref)
        if subscription is not None:
            await self._finish_cancelled_task(idle_task)
            return subscription

        stream_device = await self._monitor.open_stream_device(device_ref)
        queue: asyncio.Queue[AndroidStreamMessage] = asyncio.Queue(maxsize=1)
        async with self._guard:
            if self._closed:
                raise AppError(
                    code="ANDROID_STREAM_UNAVAILABLE",
                    message="实时监看服务正在关闭",
                    status_code=503,
                    retryable=True,
                )
            producer = self._producers.get(device_ref)
            if producer is None:
                producer = _Producer(device_ref=device_ref, stream_device=stream_device)
                producer.subscribers.add(queue)
                self._producers[device_ref] = producer
                producer.task = asyncio.create_task(
                    self._run_producer(producer),
                    name=f"android-stream:{device_ref}",
                )
                idle_task = None
            else:
                producer.subscribers.add(queue)
                idle_task = self._cancel_idle_locked(producer)
        await self._finish_cancelled_task(idle_task)
        return AndroidDeviceStreamSubscription(self, device_ref, queue)

    async def _subscribe_existing(
        self,
        device_ref: str,
    ) -> tuple[AndroidDeviceStreamSubscription | None, asyncio.Task[None] | None]:
        async with self._guard:
            if self._closed:
                raise AppError(
                    code="ANDROID_STREAM_UNAVAILABLE",
                    message="实时监看服务正在关闭",
                    status_code=503,
                    retryable=True,
                )
            producer = self._producers.get(device_ref)
            if producer is None:
                return None, None
            queue: asyncio.Queue[AndroidStreamMessage] = asyncio.Queue(maxsize=1)
            producer.subscribers.add(queue)
            idle_task = self._cancel_idle_locked(producer)
            return AndroidDeviceStreamSubscription(self, device_ref, queue), idle_task

    @staticmethod
    def _cancel_idle_locked(producer: _Producer) -> asyncio.Task[None] | None:
        idle_task = producer.idle_task
        producer.idle_task = None
        if idle_task is not None:
            idle_task.cancel()
        return idle_task

    @staticmethod
    async def _finish_cancelled_task(task: asyncio.Task[None] | None) -> None:
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _unsubscribe(
        self,
        device_ref: str,
        queue: asyncio.Queue[AndroidStreamMessage],
    ) -> None:
        task_to_stop: asyncio.Task[None] | None = None
        async with self._guard:
            producer = self._producers.get(device_ref)
            if producer is None:
                return
            producer.subscribers.discard(queue)
            if producer.subscribers:
                return
            if self._idle_grace_seconds == 0:
                self._producers.pop(device_ref, None)
                task_to_stop = producer.task
            elif producer.idle_task is None:
                producer.idle_task = asyncio.create_task(
                    self._stop_after_idle(producer),
                    name=f"android-stream-idle:{device_ref}",
                )
        if task_to_stop is not None:
            task_to_stop.cancel()
            await asyncio.gather(task_to_stop, return_exceptions=True)

    async def _stop_after_idle(self, producer: _Producer) -> None:
        try:
            await asyncio.sleep(self._idle_grace_seconds)
            task_to_stop: asyncio.Task[None] | None = None
            async with self._guard:
                current = self._producers.get(producer.device_ref)
                if current is producer and not producer.subscribers:
                    self._producers.pop(producer.device_ref, None)
                    producer.idle_task = None
                    task_to_stop = producer.task
            if task_to_stop is not None:
                task_to_stop.cancel()
                await asyncio.gather(task_to_stop, return_exceptions=True)
        except asyncio.CancelledError:
            raise

    async def _run_producer(self, producer: _Producer) -> None:
        last_success_at: float | None = None
        next_recheck_at = time.monotonic() + self._device_recheck_seconds
        backoff_seconds = min(
            max(self._interval_seconds, 0.1),
            self._max_backoff_seconds,
        )
        try:
            while True:
                started_at = time.monotonic()
                should_recheck = started_at >= next_recheck_at
                try:
                    screenshot = await self._monitor.capture_stream_frame(
                        producer.stream_device,
                        recheck=should_recheck,
                    )
                    if should_recheck:
                        next_recheck_at = time.monotonic() + self._device_recheck_seconds
                except asyncio.CancelledError:
                    raise
                except AppError as error:
                    stream_error = await self._classify_error(producer.stream_device, error)
                    if stream_error.terminal:
                        await self._retire_and_publish_terminal(producer, stream_error)
                        return
                    self._publish_latest(producer, stream_error)
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(
                        max(backoff_seconds * 2, 0.1),
                        self._max_backoff_seconds,
                    )
                    continue
                except Exception as error:
                    logger.error(
                        "android_stream_capture_failed",
                        deviceRef=producer.device_ref,
                        errorType=type(error).__name__,
                    )
                    stream_error = AndroidStreamError(
                        code="ANDROID_STREAM_ERROR",
                        message="实时画面暂时不可用",
                        retryable=True,
                        terminal=True,
                    )
                    await self._retire_and_publish_terminal(producer, stream_error)
                    return

                completed_at = time.monotonic()
                producer.sequence += 1
                effective_fps = (
                    None
                    if last_success_at is None
                    else 1 / max(completed_at - last_success_at, 0.001)
                )
                last_success_at = completed_at
                self._publish_latest(
                    producer,
                    AndroidStreamFrame(
                        content=screenshot.content,
                        captured_at=screenshot.captured_at,
                        sequence=producer.sequence,
                        effective_fps=effective_fps,
                    ),
                )
                backoff_seconds = min(
                    max(self._interval_seconds, 0.1),
                    self._max_backoff_seconds,
                )
                remaining = self._interval_seconds - (time.monotonic() - started_at)
                if remaining > 0:
                    await asyncio.sleep(remaining)
        finally:
            await self._producer_finished(producer)

    async def _classify_error(
        self,
        stream_device: AndroidStreamDevice,
        error: AppError,
    ) -> AndroidStreamError:
        if error.code in _TERMINAL_DEVICE_CODES:
            return self._to_stream_error(error, terminal=True)
        try:
            await self._monitor.revalidate_stream_device(stream_device)
        except AppError as revalidation_error:
            if revalidation_error.code in _TERMINAL_DEVICE_CODES:
                return self._to_stream_error(revalidation_error, terminal=True)
        except Exception as revalidation_error:
            logger.error(
                "android_stream_revalidation_failed",
                deviceRef=stream_device.device_ref,
                errorType=type(revalidation_error).__name__,
            )
            return AndroidStreamError(
                code="ANDROID_STREAM_ERROR",
                message="实时画面暂时不可用",
                retryable=True,
                terminal=True,
            )
        return self._to_stream_error(error, terminal=not error.retryable)

    @staticmethod
    def _to_stream_error(error: AppError, *, terminal: bool) -> AndroidStreamError:
        return AndroidStreamError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            terminal=terminal,
        )

    @staticmethod
    def _publish_latest(producer: _Producer, message: AndroidStreamMessage) -> None:
        for queue in tuple(producer.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    async def _retire_and_publish_terminal(
        self,
        producer: _Producer,
        message: AndroidStreamError,
    ) -> None:
        idle_task: asyncio.Task[None] | None = None
        async with self._guard:
            if self._producers.get(producer.device_ref) is producer:
                self._producers.pop(producer.device_ref, None)
                idle_task = self._cancel_idle_locked(producer)
            self._publish_latest(producer, message)
        if idle_task is not asyncio.current_task():
            await self._finish_cancelled_task(idle_task)

    async def _producer_finished(self, producer: _Producer) -> None:
        idle_task: asyncio.Task[None] | None = None
        async with self._guard:
            if self._producers.get(producer.device_ref) is producer:
                self._producers.pop(producer.device_ref, None)
                idle_task = self._cancel_idle_locked(producer)
        if idle_task is not asyncio.current_task():
            await self._finish_cancelled_task(idle_task)

    async def shutdown(self) -> None:
        async with self._guard:
            if self._closed:
                return
            self._closed = True
            producers = list(self._producers.values())
            self._producers.clear()
            idle_tasks = [
                task
                for producer in producers
                if (task := self._cancel_idle_locked(producer)) is not None
            ]
            producer_tasks = [producer.task for producer in producers if producer.task is not None]
        for task in [*idle_tasks, *producer_tasks]:
            task.cancel()
        await asyncio.gather(*idle_tasks, *producer_tasks, return_exceptions=True)
