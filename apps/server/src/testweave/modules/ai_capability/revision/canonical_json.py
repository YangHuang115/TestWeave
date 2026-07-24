import hashlib
import json
import math
from typing import Any

from testweave.core.errors import AppError


def _sort_and_clean_value(val: Any, depth: int = 0) -> Any:
    if depth > 100:
        raise AppError(
            code="REVISION_SCHEMA_INVALID",
            message="JSON 深度超过 100 层限制",
            status_code=400,
        )

    if val is None:
        return None
    elif isinstance(val, bool):
        return val
    elif isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            raise AppError(
                code="REVISION_SCHEMA_INVALID",
                message="Canonical JSON 拒绝 NaN 与 Infinity",
                status_code=400,
            )
        # 精确格式化浮点数或整数
        return val
    elif isinstance(val, str):
        return val
    elif isinstance(val, list):
        return [_sort_and_clean_value(item, depth + 1) for item in val]
    elif isinstance(val, dict):
        # 按 key 字典序排序
        sorted_dict = {}
        for k in sorted(val.keys()):
            if not isinstance(k, str):
                raise AppError(
                    code="REVISION_SCHEMA_INVALID",
                    message="JSON key 必须为字符串",
                    status_code=400,
                )
            sorted_dict[k] = _sort_and_clean_value(val[k], depth + 1)
        return sorted_dict
    else:
        raise AppError(
            code="REVISION_SCHEMA_INVALID",
            message=f"不支持的数据类型: {type(val)}",
            status_code=400,
        )


def canonicalize_json(data: Any) -> str:
    """生成符合 m09-canonical-json-v1 规范的标准 JSON 文本。"""
    cleaned = _sort_and_clean_value(data)
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def calculate_canonical_hash(data: Any) -> str:
    """计算 Canonical JSON 的 SHA-256 哈希 (小写十六进制)。"""
    canonical_str = canonicalize_json(data)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
