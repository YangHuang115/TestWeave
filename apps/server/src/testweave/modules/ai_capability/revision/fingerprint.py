import hashlib
from typing import Any

from testweave.modules.ai_capability.revision.canonical_json import canonicalize_json


def calculate_input_fingerprint(
    capability_version_id: str,
    package_fingerprint: str,
    execution_snapshot_hash: str,
    node_id: str,
    node_config: dict[str, Any],
    run_input: dict[str, Any],
    upstream_set_hashes: list[dict[str, str]],  # [{"node_id": "...", "set_hash": "..."}]
    human_decision_snapshot: dict[str, Any] | None = None,
    project_rules: dict[str, Any] | None = None,
    skill_prompt_versions: dict[str, Any] | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> str:
    """计算符合 m09-input-fingerprint-v1 规范的输入指纹。"""
    # 按照稳定 node_id 排序上游集合哈希
    sorted_upstream = sorted(upstream_set_hashes, key=lambda x: x.get("node_id", ""))

    payload = {
        "algorithm": "m09-input-fingerprint-v1",
        "capability_version_id": str(capability_version_id),
        "package_fingerprint": package_fingerprint,
        "execution_snapshot_hash": execution_snapshot_hash,
        "node_id": node_id,
        "node_config": node_config or {},
        "run_input": run_input or {},
        "upstream_set_hashes": sorted_upstream,
        "human_decision_snapshot": human_decision_snapshot or {},
        "project_rules": project_rules or {},
        "skill_prompt_versions": skill_prompt_versions or {},
        "provider_name": provider_name or "",
        "model_name": model_name or "",
    }

    canonical_str = canonicalize_json(payload)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
