import uuid
from typing import Any

from testweave.core.errors import AppError


def parse_json_pointer(pointer: str) -> list[str]:
    """解析 RFC 6901 JSON Pointer。"""
    if not pointer:
        return []
    if not pointer.startswith("/"):
        raise AppError(
            code="LOCK_POINTER_INVALID",
            message=f"不合法的 JSON Pointer: {pointer}",
            status_code=400,
        )
    parts = pointer.split("/")[1:]
    return [p.replace("~1", "/").replace("~0", "~") for p in parts]


def get_value_by_json_pointer(doc: Any, pointer: str) -> Any:
    """根据 RFC 6901 JSON Pointer 获取文档对应节点的值。"""
    if not pointer or pointer == "/" or pointer == "":
        return doc

    tokens = parse_json_pointer(pointer)
    curr = doc
    for token in tokens:
        if isinstance(curr, dict):
            if token not in curr:
                raise AppError(
                    code="LOCK_POINTER_INVALID",
                    message=f"Pointer 路径不存在: {pointer} (missing key: {token})",
                    status_code=400,
                )
            curr = curr[token]
        elif isinstance(curr, list):
            try:
                idx = int(token)
                curr = curr[idx]
            except (ValueError, IndexError) as exc:
                raise AppError(
                    code="LOCK_POINTER_INVALID",
                    message=f"Pointer 路径在数组中位置非法: {pointer} (index: {token})",
                    status_code=400,
                ) from exc
        else:
            raise AppError(
                code="LOCK_POINTER_INVALID",
                message=f"Pointer 尝试穿透标量节点: {pointer}",
                status_code=400,
            )
    return curr


def extract_items_from_output(
    output_data: dict[str, Any],
    projection_config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """从节点输出数据提取条目数组。
    如果缺少 projection_config，视整个 output_data 为单一或默认集合。
    """
    if not projection_config:
        # Fallback: 查看是否自带 "test_points" 或 "items"
        if "test_points" in output_data and isinstance(output_data["test_points"], list):
            return output_data["test_points"]
        elif "items" in output_data and isinstance(output_data["items"], list):
            return output_data["items"]
        else:
            return [output_data]

    pointer = projection_config.get("collection_pointer", "/test_points")
    try:
        val = get_value_by_json_pointer(output_data, pointer)
        if isinstance(val, list):
            return val
        return [val]
    except Exception:
        # 如果 Pointer 获取失败，尝试常见 key
        if "test_points" in output_data and isinstance(output_data["test_points"], list):
            return output_data["test_points"]
        return [output_data]


def generate_item_stable_key(item: dict[str, Any], index: int) -> str:
    """生成稳定身份 key。
    优先读取项中的 id / item_id / code / stable_key，若不存在使用系统 UUID 分配策略。
    """
    for key in ("stableKey", "stable_key", "id", "item_id", "code", "key"):
        if key in item and item[key] is not None:
            return str(item[key])
    # 如果都不存在，使用唯一的 UUID 保持稳定身份映射
    return f"item-{index + 1}-{uuid.uuid4().hex[:8]}"
