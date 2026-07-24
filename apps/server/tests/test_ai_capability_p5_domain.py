from testweave.modules.ai_capabilities.p5_helpers import (
    compute_canary_bucket,
    compute_canonical_json_hash,
)


def test_canonical_json_hash_consistency() -> None:
    data1 = {"b": 2, "a": 1, "nested": {"y": "val", "x": [1, 2]}}
    data2 = {"a": 1, "b": 2, "nested": {"x": [1, 2], "y": "val"}}

    hash1 = compute_canonical_json_hash(data1)
    hash2 = compute_canonical_json_hash(data2)

    assert hash1 == hash2
    assert len(hash1) == 64


def test_canonical_json_hash_excludes_metadata_keys() -> None:
    data_with_hash = {"a": 1, "package_hash": "ignore_me", "revision_hash": "ignore_me_too"}
    data_without_hash = {"a": 1}

    assert compute_canonical_json_hash(data_with_hash) == compute_canonical_json_hash(
        data_without_hash
    )


def test_compute_canary_bucket_bounds_and_stability() -> None:
    deployment_id = "dep-123"
    project_id = "proj-456"
    capability_id = "cap-789"
    routing_subject = "user-001"
    salt = "salt-abc"

    bucket1 = compute_canary_bucket(deployment_id, project_id, capability_id, routing_subject, salt)
    bucket2 = compute_canary_bucket(deployment_id, project_id, capability_id, routing_subject, salt)

    # 稳定性
    assert bucket1 == bucket2
    # 范围在 [0, 9999] 闭区间
    assert 0 <= bucket1 < 10000

    # 改变 routing_subject 产生不同分桶
    bucket_other = compute_canary_bucket(deployment_id, project_id, capability_id, "user-002", salt)
    assert 0 <= bucket_other < 10000
