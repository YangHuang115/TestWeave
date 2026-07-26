"""run_agent.py 三模式（local/connected/share）验收测试。

覆盖：无 Token 启动、local 模式零 HTTP、Skill 发现与 Schema 校验、
链式记录 CLI 流转、模式解析、connected 最小权限行为、share 只创建
SYNCED_DRAFT、外接 Agent 无发布能力、gitignore 防泄漏。
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_agent
from run_agent import (
    StandaloneExternalAgentClient,
    WorkspacePaths,
    build_parser,
    discover_skills,
    load_workflow,
    resolve_mode,
    run_connected,
    run_share,
    validate_json_schema,
)

REAL_WORKSPACE = Path(__file__).resolve().parent
EXPECTED_SKILLS = [
    "requirement-analysis",
    "test-case-generation",
    "test-case-review",
    "test-point-generation",
]


def _forbid_http(*_args, **_kwargs):
    raise AssertionError("local 模式禁止发起 HTTP 请求")


def _make_workspace(root: Path) -> None:
    """构造一个最小可用的临时工作区（单阶段流程 + demo Skill）。"""
    skill_dir = root / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo-skill\n", encoding="utf-8")
    (skill_dir / "prompt.md").write_text("PROMPT\n", encoding="utf-8")
    (skill_dir / "CHANGELOG.md").write_text("## 1.0.0\n", encoding="utf-8")
    (skill_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                'protocol_version: "1.0"',
                "skill:",
                '  id: "demo-skill"',
                '  version: "1.0.0"',
                '  name: "Demo"',
                '  prompt: "prompt.md"',
                '  input_schema: "input.schema.json"',
                '  output_schema: "output.schema.json"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (skill_dir / "input.schema.json").write_text(
        json.dumps({"type": "object"}), encoding="utf-8"
    )
    (skill_dir / "output.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    capability_dir = root / "capabilities" / "ai-test-design"
    capability_dir.mkdir(parents=True)
    (capability_dir / "workflow.yaml").write_text(
        "\n".join(
            [
                'capability: "ai-test-design"',
                'version: "1.0.0"',
                "allow_pause_resume: true",
                "stages:",
                '  - key: "demo-skill"',
                '    skill: "demo-skill"',
                '    input_from: "initial"',
                "    human_confirmation: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _CapturingClient(StandaloneExternalAgentClient):
    def __init__(self) -> None:
        super().__init__(token="tw_ext_test")
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        headers_extra: dict | None = None,
    ) -> dict:
        self.calls.append((method, path, payload))
        return {"status": "SYNCED_DRAFT", "candidateId": "cand-1", "tasks": []}


class _NoTokenEnv(unittest.TestCase):
    """基类：隔离环境变量并禁止真实 HTTP。"""

    def setUp(self) -> None:
        patcher_env = mock.patch.dict(os.environ)
        patcher_env.start()
        self.addCleanup(patcher_env.stop)
        os.environ.pop("TESTWEAVE_AGENT_TOKEN", None)
        os.environ.pop("TESTWEAVE_GATEWAY_URL", None)

        patcher_http = mock.patch.object(
            run_agent.urllib.request, "urlopen", _forbid_http
        )
        patcher_http.start()
        self.addCleanup(patcher_http.stop)

        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        _make_workspace(self.workspace)

    def _main(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = run_agent.main(["--workspace-dir", str(self.workspace), *argv])
        return code, buffer.getvalue()


class LocalModeTests(_NoTokenEnv):
    def test_local_mode_starts_without_token(self) -> None:
        code, output = self._main([])
        self.assertEqual(code, 0)
        self.assertIn("local 模式", output)
        self.assertIn("无需 Token", output)

    def test_local_mode_full_record_chain_without_http(self) -> None:
        # 创建记录 → 提交阶段输出 → 人工确认 → 完成；全程 urlopen 被禁用
        code, _ = self._main(["--record-start", "--title", "登录需求", "--input", "spec text"])
        self.assertEqual(code, 0)
        store = WorkspacePaths(self.workspace).record_store()
        record_id = store.list_records()[0]["recordId"]

        output_file = self.workspace / "out.json"
        output_file.write_text(json.dumps({"result": "ok"}), encoding="utf-8")
        code, _ = self._main(
            ["--record-submit", record_id, "--stage", "demo-skill", "--output", str(output_file)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(store.load(record_id)["status"], "WAITING_HUMAN")

        code, _ = self._main(["--record-approve", record_id, "--stage", "demo-skill"])
        self.assertEqual(code, 0)
        self.assertEqual(store.load(record_id)["status"], "COMPLETED")

    def test_local_mode_schema_failure_blocks_submit(self) -> None:
        self._main(["--record-start", "--title", "t"])
        store = WorkspacePaths(self.workspace).record_store()
        record_id = store.list_records()[0]["recordId"]
        bad_file = self.workspace / "bad.json"
        bad_file.write_text(json.dumps({"unexpected": 1}), encoding="utf-8")
        code, output = self._main(
            ["--record-submit", record_id, "--stage", "demo-skill", "--output", str(bad_file)]
        )
        self.assertEqual(code, 1)
        self.assertIn("未通过 demo-skill output Schema 校验", output)

    def test_local_mode_pause_and_resume_via_cli(self) -> None:
        self._main(["--record-start", "--title", "t"])
        store = WorkspacePaths(self.workspace).record_store()
        record_id = store.list_records()[0]["recordId"]
        code, _ = self._main(["--record-pause", record_id])
        self.assertEqual(code, 0)
        self.assertEqual(store.load(record_id)["status"], "PAUSED")
        code, _ = self._main(["--record-resume", record_id])
        self.assertEqual(code, 0)
        self.assertEqual(store.load(record_id)["status"], "ACTIVE")

    def test_local_mode_rejects_connected_and_share_flags(self) -> None:
        code, output = self._main(["--sync-skills", "--mode", "local"])
        self.assertEqual(code, 1)
        self.assertIn("--mode share", output)

        code, output = self._main(["--mode", "local", "--list-tasks"])
        self.assertEqual(code, 1)
        self.assertIn("--mode connected", output)

    def test_list_skills_and_show_workflow(self) -> None:
        code, output = self._main(["--list-skills"])
        self.assertEqual(code, 0)
        self.assertIn("demo-skill v1.0.0", output)
        code, output = self._main(["--show-workflow"])
        self.assertEqual(code, 0)
        self.assertIn("demo-skill", output)
        self.assertIn("人工确认", output)


class ModeResolutionTests(unittest.TestCase):
    def _resolve(self, argv: list[str]) -> str:
        return resolve_mode(build_parser().parse_args(argv))

    def test_default_is_local(self) -> None:
        self.assertEqual(self._resolve([]), "local")
        self.assertEqual(self._resolve(["--list-skills"]), "local")

    def test_sync_skills_is_share_alias(self) -> None:
        self.assertEqual(self._resolve(["--sync-skills"]), "share")
        self.assertEqual(self._resolve(["--sync-skills", "requirement-analysis"]), "share")

    def test_message_and_connected_flags_resolve_connected(self) -> None:
        self.assertEqual(self._resolve(["继续处理任务"]), "connected")
        self.assertEqual(self._resolve(["--list-tasks"]), "connected")
        self.assertEqual(self._resolve(["--submit-candidate"]), "connected")

    def test_explicit_mode_wins(self) -> None:
        self.assertEqual(self._resolve(["--mode", "local"]), "local")
        self.assertEqual(self._resolve(["--mode", "share"]), "share")


class TokenGateTests(_NoTokenEnv):
    def test_connected_without_token_exits_with_guidance(self) -> None:
        code, output = self._main(["--mode", "connected"])
        self.assertEqual(code, 1)
        self.assertIn("test_task.read", output)
        self.assertIn("revision:candidate", output)
        self.assertNotIn("skill:sync", output)

    def test_share_without_token_exits_with_guidance(self) -> None:
        code, output = self._main(["--mode", "share", "--sync-skills"])
        self.assertEqual(code, 1)
        self.assertIn("skill:sync", output)


class RealWorkspaceTests(unittest.TestCase):
    def test_four_skills_discoverable_and_valid(self) -> None:
        skills, errors = discover_skills(REAL_WORKSPACE / "skills")
        self.assertEqual(errors, {})
        self.assertEqual(sorted(skills), EXPECTED_SKILLS)
        for skill in skills.values():
            self.assertTrue(skill["fingerprint"].startswith("sha256:"))

    def test_workflow_defines_four_stage_chain(self) -> None:
        workflow = load_workflow(REAL_WORKSPACE / "capabilities" / "ai-test-design")
        self.assertEqual(
            [stage["key"] for stage in workflow["stages"]],
            [
                "requirement-analysis",
                "test-point-generation",
                "test-case-generation",
                "test-case-review",
            ],
        )
        for stage in workflow["stages"]:
            self.assertTrue(stage.get("human_confirmation"))

    def test_sample_outputs_pass_output_schema(self) -> None:
        skills, _ = discover_skills(REAL_WORKSPACE / "skills")
        for skill in skills.values():
            sample = skill["dir"] / "examples" / "sample-output.json"
            self.assertTrue(sample.is_file(), f"{skill['id']} 缺少 sample-output.json")
            payload = json.loads(sample.read_text(encoding="utf-8"))
            errors = validate_json_schema(payload, skill["output_schema"])
            self.assertEqual(errors, [], f"{skill['id']} 示例输出未通过 Schema 校验")


class ConnectedModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        _make_workspace(self.workspace)
        self.paths = WorkspacePaths(self.workspace)

    def _run_connected(self, argv: list[str], client: _CapturingClient) -> tuple[int, str]:
        args = build_parser().parse_args(["--workspace-dir", str(self.workspace), *argv])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = run_connected(args, self.paths, client)
        return code, buffer.getvalue()

    def test_list_tasks_uses_only_task_endpoint(self) -> None:
        client = _CapturingClient()
        code, _ = self._run_connected(["--list-tasks"], client)
        self.assertEqual(code, 0)
        self.assertEqual(client.calls, [("GET", "/external/v1/tasks", None)])

    def test_connected_never_syncs_skills(self) -> None:
        client = _CapturingClient()
        code, output = self._run_connected(["--mode", "connected", "--sync-skills"], client)
        self.assertEqual(code, 1)
        self.assertEqual(client.calls, [])
        self.assertIn("--mode share", output)

    def test_submit_candidate_keeps_auto_publish_false(self) -> None:
        payload_file = self.workspace / "payload.json"
        payload_file.write_text(json.dumps({"result": "ok"}), encoding="utf-8")
        client = _CapturingClient()
        code, _ = self._run_connected(
            [
                "--submit-candidate",
                "--artifact-type",
                "test_point_set@1.0",
                "--payload-file",
                str(payload_file),
            ],
            client,
        )
        self.assertEqual(code, 0)
        method, path, body = client.calls[0]
        self.assertEqual((method, path), ("POST", "/external/v1/revision/candidates"))
        self.assertIs(body["autoPublish"], False)


class ShareModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name)
        _make_workspace(self.workspace)
        self.paths = WorkspacePaths(self.workspace)

    def test_share_only_creates_synced_draft(self) -> None:
        client = _CapturingClient()
        args = build_parser().parse_args(
            ["--workspace-dir", str(self.workspace), "--mode", "share", "--sync-skills"]
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = run_share(args, self.paths, client)
        self.assertEqual(code, 0)
        self.assertTrue(client.calls)
        for method, path, _payload in client.calls:
            self.assertEqual((method, path), ("POST", "/external/v1/skills/sync-draft"))
        self.assertIn("SYNCED_DRAFT", buffer.getvalue())
        self.assertIn("agent.manage", buffer.getvalue())

    def test_external_client_has_no_publish_capability(self) -> None:
        publish_members = [
            name
            for name in dir(StandaloneExternalAgentClient)
            if "publish" in name.lower()
        ]
        self.assertEqual(publish_members, [])


class GitIgnoreTests(unittest.TestCase):
    def test_workspace_gitignore_covers_secrets_and_runs(self) -> None:
        entries = (REAL_WORKSPACE / ".gitignore").read_text(encoding="utf-8").splitlines()
        for required in (".env.local", "runs/", "*.token", "*.secret"):
            self.assertIn(required, entries)

    def test_repo_gitignore_covers_workspace_runs(self) -> None:
        repo_ignore = (REAL_WORKSPACE.parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("external_agent_workspace/runs/", repo_ignore)


if __name__ == "__main__":
    unittest.main()
