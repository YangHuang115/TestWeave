import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_workspace_runner() -> ModuleType:
    runner_path = Path(__file__).resolve().parents[3] / "external_agent_workspace" / "run_agent.py"
    spec = importlib.util.spec_from_file_location(
        "testweave_external_workspace_runner", runner_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready_workbench() -> dict[str, Any]:
    return {
        "status": "READY",
        "readOnly": True,
        "intent": {
            "message": "继续处理 TASK-LOGIN-001 的测试点生成",
            "stage": "test-points",
            "artifactType": "test_point_set@1.0",
        },
        "project": {
            "id": "project-id",
            "key": "DEMO",
            "name": "演示项目",
        },
        "workbench": {
            "version": {
                "id": "version-id",
                "key": "0.0.1",
                "name": "0.0.1 demo版本",
                "status": "ACTIVE",
            },
            "task": {
                "id": "11111111-1111-1111-1111-111111111111",
                "key": "TASK-LOGIN-001",
                "title": "用户登录用例设计",
                "status": "IN_PROGRESS",
                "taskType": "CASE_DESIGN",
                "priority": "HIGH",
                "updatedAt": "2026-07-24T00:00:00+00:00",
            },
            "requirements": [
                {
                    "id": "requirement-id",
                    "key": "REQ-21001",
                    "title": "用户登录与会话",
                    "status": "READY",
                    "priority": "HIGH",
                }
            ],
            "aiDesign": None,
        },
        "entryPoint": {
            "action": "LOAD_TASK_CONTEXT",
            "method": "GET",
            "path": "/external/v1/tasks/11111111-1111-1111-1111-111111111111",
            "taskId": "11111111-1111-1111-1111-111111111111",
            "taskKey": "TASK-LOGIN-001",
            "stage": "test-points",
            "artifactType": "test_point_set@1.0",
        },
        "candidates": [],
        "blockers": [],
    }


def test_workspace_runner_renders_only_workbench_content() -> None:
    module = _load_workspace_runner()

    rendered = module.render_workbench(_ready_workbench())

    assert "# 当前工作台" in rendered
    assert "演示项目" in rendered
    assert "TASK-LOGIN-001" in rendered
    assert "REQ-21001" in rendered
    assert "# 直接执行入口" in rendered
    assert "回复“继续”即可直接读取任务上下文" in rendered
    assert "Gateway Session" not in rendered
    assert "Access Token" not in rendered


def test_workspace_runner_executes_only_safe_ready_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_workspace_runner()
    client = module.StandaloneExternalAgentClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del headers_extra
        calls.append((method, path, payload))
        return {"task": "loaded"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.execute_workbench_entry(_ready_workbench())

    assert result == {"task": "loaded"}
    assert calls == [("GET", "/external/v1/tasks/11111111-1111-1111-1111-111111111111", None)]


def test_workspace_runner_refuses_non_uuid_task_entry() -> None:
    module = _load_workspace_runner()
    client = module.StandaloneExternalAgentClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )
    workbench = _ready_workbench()
    workbench["entryPoint"]["path"] = "/external/v1/tasks/.."
    workbench["entryPoint"]["taskId"] = ".."

    with pytest.raises(ValueError):
        client.execute_workbench_entry(workbench)


def test_workspace_runner_submits_candidate_without_auto_publish_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_workspace_runner()
    client = module.StandaloneExternalAgentClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )
    recorded_payload: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del headers_extra
        assert method == "POST"
        assert path == "/external/v1/revision/candidates"
        assert payload is not None
        recorded_payload.update(payload)
        return {"status": "SUBMITTED"}

    monkeypatch.setattr(client, "_request", fake_request)

    client.submit_candidate(
        artifact_type="test_point_set@1.0",
        payload={"points": []},
        task_id="task-id",
    )

    assert recorded_payload["autoPublish"] is False


def test_workspace_runner_does_not_expose_auto_publish_option() -> None:
    module = _load_workspace_runner()
    client = module.StandaloneExternalAgentClient(
        gateway_url="http://127.0.0.1:8787",
        token="tw_ext_test",
    )

    with pytest.raises(TypeError):
        client.submit_candidate(
            artifact_type="test_point_set@1.0",
            payload={"points": []},
            auto_publish=True,
        )
