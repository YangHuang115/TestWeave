import pytest

from testweave.core.errors import AppError
from testweave.modules.ai_capability.revision import (
    calculate_canonical_hash,
    calculate_input_fingerprint,
    canonicalize_json,
)


def test_canonical_json_key_sorting() -> None:
    data1 = {"b": 2, "a": 1, "c": {"y": 20, "x": 10}}
    data2 = {"a": 1, "c": {"x": 10, "y": 20}, "b": 2}

    json1 = canonicalize_json(data1)
    json2 = canonicalize_json(data2)

    assert json1 == json2
    assert json1 == '{"a":1,"b":2,"c":{"x":10,"y":20}}'
    assert calculate_canonical_hash(data1) == calculate_canonical_hash(data2)


def test_canonical_json_rejects_nan_inf() -> None:
    with pytest.raises(AppError) as exc:
        canonicalize_json({"value": float("nan")})
    assert exc.value.code == "REVISION_SCHEMA_INVALID"

    with pytest.raises(AppError) as exc2:
        canonicalize_json({"value": float("inf")})
    assert exc2.value.code == "REVISION_SCHEMA_INVALID"


def test_input_fingerprint_stability() -> None:
    fp1 = calculate_input_fingerprint(
        capability_version_id="cap-v1",
        package_fingerprint="pkg-fp-123",
        execution_snapshot_hash="snap-hash-456",
        node_id="node_a",
        node_config={"mode": "fast"},
        run_input={"req_id": "REQ-10006"},
        upstream_set_hashes=[
            {"node_id": "up_1", "set_hash": "hash1"},
            {"node_id": "up_2", "set_hash": "hash2"},
        ],
    )

    # 颠倒上游顺序，指纹仍须保持一致
    fp2 = calculate_input_fingerprint(
        capability_version_id="cap-v1",
        package_fingerprint="pkg-fp-123",
        execution_snapshot_hash="snap-hash-456",
        node_id="node_a",
        node_config={"mode": "fast"},
        run_input={"req_id": "REQ-10006"},
        upstream_set_hashes=[
            {"node_id": "up_2", "set_hash": "hash2"},
            {"node_id": "up_1", "set_hash": "hash1"},
        ],
    )

    assert fp1 == fp2
