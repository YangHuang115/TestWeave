import hashlib
import json
from typing import Any


def calculate_json_hash(data: Any) -> str:
    """对标准 JSON 结构进行确定性 SHA-256 计算"""
    json_bytes = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()


class ExecutionSnapshotBuilder:
    """P2 运行执行快照构建与散列计算器"""

    @classmethod
    def build_snapshot(
        cls,
        capability_id: str,
        capability_version_id: str,
        package_fingerprint: str,
        workflow_snapshot: dict[str, Any],
        package_files: dict[str, str],
        model_provider_type: str,
        model_name: str,
    ) -> tuple[dict[str, Any], str]:
        snapshot = {
            "capability_id": str(capability_id),
            "capability_version_id": str(capability_version_id),
            "package_fingerprint": package_fingerprint,
            "workflow": workflow_snapshot,
            "package_files": package_files,
            "provider": {
                "provider_type": model_provider_type,
                "model_name": model_name,
            },
            "registry_version": "v1",
        }
        snapshot_hash = calculate_json_hash(snapshot)
        return snapshot, snapshot_hash
