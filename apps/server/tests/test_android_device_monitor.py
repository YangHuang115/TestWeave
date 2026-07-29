from dataclasses import dataclass

import pytest

from testweave.core.errors import AppError
from testweave.modules.android_device_monitor.service import AndroidDeviceMonitorService


@dataclass
class FakeDevice:
    device_id: str
    state: str
    model: str | None = None


class FakeAdapter:
    def __init__(self) -> None:
        self.devices = [FakeDevice("emulator-5554", "online", "Pixel 8")]
        self.info_calls: list[str] = []
        self.screenshot_calls: list[str] = []

    async def list_devices(self) -> list[FakeDevice]:
        return list(self.devices)

    async def get_device_info(self, device_id: str) -> dict[str, str]:
        self.info_calls.append(device_id)
        return {"device_id": device_id, "model": "Pixel 8", "android_version": "15"}

    async def screenshot(self, device_id: str) -> bytes:
        self.screenshot_calls.append(device_id)
        return b"\x89PNG\r\n\x1a\n" + b"x"


def test_list_devices_returns_opaque_refs_and_skips_unavailable_info() -> None:
    import asyncio

    adapter = FakeAdapter()
    adapter.devices.append(FakeDevice("R58M1234", "offline", "Galaxy S23"))
    service = AndroidDeviceMonitorService(adapter, secret="unit-test-secret")

    response = asyncio.run(service.list_devices())

    assert response.total == 2
    assert response.items[0].device_ref.startswith("v1_")
    assert response.items[0].device_ref != "emulator-5554"
    assert response.items[0].info_available is True
    assert response.items[1].info_available is False
    assert adapter.info_calls == ["emulator-5554"]


def test_screenshot_resolves_ref_against_latest_device_list() -> None:
    import asyncio

    adapter = FakeAdapter()
    service = AndroidDeviceMonitorService(adapter, secret="unit-test-secret")
    devices = asyncio.run(service.list_devices())

    image = asyncio.run(service.screenshot(devices.items[0].device_ref))

    assert image.media_type == "image/png"
    assert adapter.screenshot_calls == ["emulator-5554"]


def test_screenshot_does_not_call_unavailable_device() -> None:
    import asyncio

    adapter = FakeAdapter()
    adapter.devices = [FakeDevice("R58M1234", "unauthorized", "Galaxy S23")]
    service = AndroidDeviceMonitorService(adapter, secret="unit-test-secret")
    ref = service.device_ref("R58M1234")

    with pytest.raises(AppError) as error:
        asyncio.run(service.screenshot(ref))

    assert error.value.code == "ANDROID_DEVICE_UNAVAILABLE"
    assert adapter.screenshot_calls == []


def test_screenshot_rejects_unknown_ref() -> None:
    import asyncio

    service = AndroidDeviceMonitorService(FakeAdapter(), secret="unit-test-secret")

    with pytest.raises(AppError) as error:
        asyncio.run(service.screenshot("v1_unknown"))

    assert error.value.code == "ANDROID_DEVICE_NOT_FOUND"
    assert service._locks == {}


def test_screenshot_calls_are_serialized_per_device() -> None:
    # The service keeps one lock per opaque device reference; this is a cheap
    # regression guard for the no-concurrent-refresh contract.
    service = AndroidDeviceMonitorService(FakeAdapter(), secret="unit-test-secret")
    ref = service.device_ref("emulator-5554")
    assert service.device_ref("emulator-5554") == ref
    assert service.device_ref("emulator-5556") != ref


def test_manual_and_stream_screenshots_share_the_same_device_lock() -> None:
    import asyncio

    class ConcurrentAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.active_screenshots = 0
            self.max_active_screenshots = 0

        async def screenshot(self, device_id: str) -> bytes:
            self.active_screenshots += 1
            self.max_active_screenshots = max(
                self.max_active_screenshots,
                self.active_screenshots,
            )
            await asyncio.sleep(0.01)
            self.active_screenshots -= 1
            return await super().screenshot(device_id)

    async def scenario() -> int:
        adapter = ConcurrentAdapter()
        service = AndroidDeviceMonitorService(adapter, secret="unit-test-secret")
        device_ref = service.device_ref("emulator-5554")
        stream_device = await service.open_stream_device(device_ref)
        await asyncio.gather(
            service.screenshot(device_ref),
            service.capture_stream_frame(stream_device, recheck=False),
        )
        return adapter.max_active_screenshots

    assert asyncio.run(scenario()) == 1
