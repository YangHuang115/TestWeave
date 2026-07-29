import base64

import pytest

from testweave.modules.android_device_monitor.parser import (
    AndroidMcpProtocolError,
    parse_device_info,
    parse_device_list,
    parse_screenshot,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_parse_device_list_normalizes_vendor_text() -> None:
    devices = parse_device_list(
        "List of devices attached\n"
        "emulator-5554 [online] model:Pixel_8_API_35\n"
        "R58M1234ABC [unauthorized] model:Galaxy_S23\n"
        "emulator-5556 [offline] model:Pixel_7_API_34\n"
    )

    assert [device.device_id for device in devices] == [
        "emulator-5554",
        "R58M1234ABC",
        "emulator-5556",
    ]
    assert devices[0].state == "online"
    assert devices[0].model == "Pixel_8_API_35"
    assert devices[1].state == "unauthorized"


def test_parse_device_list_empty_vendor_message_returns_empty() -> None:
    assert parse_device_list("No devices found. Start an emulator with start_emulator.") == []


def test_parse_device_list_rejects_unrecognized_nonempty_text() -> None:
    with pytest.raises(AndroidMcpProtocolError):
        parse_device_list("device output changed unexpectedly")


def test_parse_device_info_accepts_key_value_text() -> None:
    info = parse_device_info("Device ID: emulator-5554\nModel: Pixel 8\nAndroid Version: 15")

    assert info == {
        "device_id": "emulator-5554",
        "model": "Pixel 8",
        "android_version": "15",
    }


def test_parse_screenshot_requires_one_png_image_block() -> None:
    block = {"type": "image", "data": base64.b64encode(PNG_BYTES).decode(), "mimeType": "image/png"}

    assert parse_screenshot([{"type": "text", "text": "captured"}, block]) == PNG_BYTES


def test_parse_screenshot_rejects_non_png_and_multiple_images() -> None:
    image = {"type": "image", "data": base64.b64encode(PNG_BYTES).decode(), "mimeType": "image/png"}
    with pytest.raises(AndroidMcpProtocolError):
        parse_screenshot([{**image, "mimeType": "image/jpeg"}])
    with pytest.raises(AndroidMcpProtocolError):
        parse_screenshot([image, image])


def test_parse_screenshot_rejects_oversized_base64_before_decoding() -> None:
    image = {
        "type": "image",
        "data": "A" * 32,
        "mimeType": "image/png",
    }

    with pytest.raises(AndroidMcpProtocolError, match="超过大小限制"):
        parse_screenshot([image], max_bytes=16)
