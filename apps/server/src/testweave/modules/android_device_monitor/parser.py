import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DEVICE_LINE = re.compile(
    r"^\s*(?P<device_id>\S+)\s+\[(?P<state>[^\]]+)\](?:\s+(?P<metadata>.*))?\s*$"
)
_MODEL = re.compile(r"(?:^|\s)model:(?P<model>\S+)", re.IGNORECASE)


class AndroidMcpProtocolError(ValueError):
    """Raised when the pinned vendor response cannot be safely normalized."""


@dataclass(frozen=True)
class ParsedDevice:
    device_id: str
    state: str
    model: str | None = None


def _normalize_state(value: str) -> str:
    state = value.strip().casefold().replace(" ", "_")
    aliases = {
        "device": "online",
        "authorized": "online",
        "no_permissions": "unauthorized",
        "no_permission": "unauthorized",
    }
    return aliases.get(state, state or "unknown")


def parse_device_list(text: str) -> list[ParsedDevice]:
    """Parse the text format returned by android-mcp-server@1.3.0."""

    if not isinstance(text, str):
        raise AndroidMcpProtocolError("设备列表响应不是文本")

    devices: list[ParsedDevice] = []
    seen: set[str] = set()
    meaningful_lines = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.casefold().startswith("list of devices"):
            continue
        match = _DEVICE_LINE.match(stripped)
        if match is None:
            meaningful_lines += 1
            continue
        meaningful_lines += 1
        device_id = match.group("device_id")
        if device_id in seen:
            raise AndroidMcpProtocolError("设备列表包含重复设备")
        seen.add(device_id)
        metadata = match.group("metadata") or ""
        model_match = _MODEL.search(metadata)
        devices.append(
            ParsedDevice(
                device_id=device_id,
                state=_normalize_state(match.group("state")),
                model=model_match.group("model") if model_match else None,
            )
        )

    if devices:
        return devices
    if meaningful_lines == 0:
        return []
    lowered = text.casefold()
    if any(
        marker in lowered
        for marker in ("no device", "no connected", "start_emulator", "no emulator")
    ):
        return []
    raise AndroidMcpProtocolError("设备列表响应格式无法识别")


def parse_device_info(text: str) -> dict[str, str]:
    if not isinstance(text, str):
        raise AndroidMcpProtocolError("设备信息响应不是文本")
    info: dict[str, str] = {}
    aliases = {
        "device id": "device_id",
        "device": "device_id",
        "id": "device_id",
        "model": "model",
        "android version": "android_version",
        "android": "android_version",
        "version": "android_version",
        "manufacturer": "manufacturer",
    }
    for line in text.splitlines():
        if ":" in line:
            raw_key, raw_value = line.split(":", 1)
        elif "=" in line:
            raw_key, raw_value = line.split("=", 1)
        else:
            continue
        key = aliases.get(raw_key.strip().casefold())
        value = raw_value.strip()
        if key and value:
            info[key] = value
    if not info:
        raise AndroidMcpProtocolError("设备信息响应格式无法识别")
    return info


def _block_value(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def parse_screenshot(
    blocks: list[Any],
    *,
    max_bytes: int = 10 * 1024 * 1024,
) -> bytes:
    images = [block for block in blocks if _block_value(block, "type") == "image"]
    if len(images) != 1:
        raise AndroidMcpProtocolError("截图响应必须且只能包含一张图片")
    block = images[0]
    mime_type = _block_value(block, "mimeType", _block_value(block, "mime_type"))
    if mime_type != "image/png":
        raise AndroidMcpProtocolError("截图必须是 PNG 图片")
    encoded = _block_value(block, "data")
    if not isinstance(encoded, (str, bytes)):
        raise AndroidMcpProtocolError("截图数据不是 Base64")
    max_encoded_bytes = 4 * ((max_bytes + 2) // 3)
    if len(encoded) > max_encoded_bytes:
        raise AndroidMcpProtocolError("截图超过大小限制")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise AndroidMcpProtocolError("截图 Base64 无效") from exc
    if len(image) > max_bytes or not image.startswith(PNG_SIGNATURE):
        raise AndroidMcpProtocolError("截图不是合法 PNG 或超过大小限制")
    return image
