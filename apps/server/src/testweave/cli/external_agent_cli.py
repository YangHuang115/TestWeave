import re
from pathlib import Path
from typing import Any

import httpx

from testweave.modules.ai_capability.external_agent.workspace_generator import (
    LocalWorkspaceGenerator,
)

TASK_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class ExternalAgentCLIClient:
    def __init__(self, gateway_url: str = "http://127.0.0.1:8787", token: str = ""):
        self.gateway_url = gateway_url.rstrip("/")
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(base_url=self.gateway_url, headers=self.headers) as client:
            response = client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()

    def check_session(self) -> dict[str, Any]:
        return self._request("GET", "/external/v1/session")

    def fetch_spec(self, target_id: str, out_dir: str | Path | None = None) -> dict[str, Any]:
        spec = self._request(
            "GET",
            f"/external/v1/workspace/spec?targetId={target_id}",
        )

        if out_dir:
            LocalWorkspaceGenerator.generate_local_workspace(spec, out_dir)

        return spec

    def submit_candidate(
        self,
        capability_id: str,
        artifact_type: str,
        payload: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/external/v1/revision/candidates",
            {
                "capabilityId": capability_id,
                "artifactType": artifact_type,
                "payload": payload,
                "summary": summary,
            },
        )

    def resolve_workbench(self, message: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/external/v1/workbench/resolve",
            {"message": message},
        )

    def execute_workbench_entry(
        self,
        workbench: dict[str, Any],
    ) -> dict[str, Any]:
        if workbench.get("status") != "READY":
            raise ValueError("工作台尚未处于 READY 状态，不能直接执行")

        entry = workbench.get("entryPoint")
        if not isinstance(entry, dict):
            raise ValueError("工作台缺少可执行入口")
        method = entry.get("method")
        path = entry.get("path")
        task_id = entry.get("taskId")
        if (
            entry.get("action") != "LOAD_TASK_CONTEXT"
            or method != "GET"
            or not isinstance(path, str)
            or not isinstance(task_id, str)
            or TASK_ID_PATTERN.fullmatch(task_id) is None
            or path != f"/external/v1/tasks/{task_id}"
        ):
            raise ValueError("工作台返回了不受支持或不安全的执行入口")

        return self._request(method, path)
