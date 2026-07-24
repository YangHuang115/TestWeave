import hashlib
import json
from typing import Any


def compute_canonical_json_hash(data: Any, exclude_keys: set[str] | None = None) -> str:
    """计算 Canonical JSON 的 SHA256 Hash 值 (排序 keys, 无多余空格, 排除指定字段)。"""
    if exclude_keys is None:
        exclude_keys = {
            "package_hash",
            "revision_hash",
            "canonical_content_hash",
            "request_fingerprint",
        }

    def _sanitize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in sorted(obj.items()) if k not in exclude_keys}
        elif isinstance(obj, list):
            return [_sanitize(x) for x in obj]
        elif isinstance(obj, float):
            # 将浮点数标准化为精确 6 位小数或干净表示
            return round(obj, 6)
        return obj

    sanitized = _sanitize(data)
    json_bytes = json.dumps(
        sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()


def compute_canary_bucket(
    deployment_id: str,
    project_id: str | None,
    capability_id: str,
    routing_subject: str,
    routing_salt: str,
) -> int:
    """根据部署配置计算灰度分桶 Bucket 值 (0..9999)。"""
    raw_str = f"{deployment_id}:{project_id or ''}:{capability_id}:{routing_subject}:{routing_salt}"
    hash_bytes = hashlib.sha256(raw_str.encode("utf-8")).digest()
    num = int.from_bytes(hash_bytes[:8], byteorder="big")
    return num % 10000
