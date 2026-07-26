"""本地链式记录（scripts/skill_records.py）验收测试。

覆盖：创建、恢复、追加 Revision、人工确认/拒绝、暂停、查询、
密钥防护、指纹隔离和阶段模型可扩展性。全部使用临时目录，不触碰真实 runs/。
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.skill_records import (
    RecordError,
    RecordStore,
    compute_directory_fingerprint,
    ensure_no_secrets,
)

TWO_STAGE_WORKFLOW = {
    "capability": "ai-test-design",
    "version": "1.0.0",
    "allow_pause_resume": True,
    "stages": [
        {
            "key": "requirement-analysis",
            "skill": "requirement-analysis",
            "input_from": "initial",
            "human_confirmation": True,
        },
        {
            "key": "test-point-generation",
            "skill": "test-point-generation",
            "input_from": "requirement-analysis",
            "human_confirmation": True,
        },
    ],
}


class RecordStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.runs_dir = Path(self._temp.name) / "runs"
        self.store = RecordStore(self.runs_dir)

    def _create(self) -> dict:
        return self.store.create(
            TWO_STAGE_WORKFLOW, title="登录需求", initial_input={"type": "text", "content": "spec"}
        )

    def test_create_record_freezes_stage_order(self) -> None:
        record = self._create()
        self.assertEqual(record["status"], "ACTIVE")
        self.assertEqual(
            record["stageOrder"], ["requirement-analysis", "test-point-generation"]
        )
        self.assertEqual(record["currentStageKey"], "requirement-analysis")
        # record.json 落盘且为合法 JSON
        on_disk = json.loads(
            (self.runs_dir / record["recordId"] / "record.json").read_text(encoding="utf-8")
        )
        self.assertEqual(on_disk["recordId"], record["recordId"])

    def test_stage_model_not_hardcoded_to_four_stages(self) -> None:
        workflow = {
            "capability": "demo",
            "stages": [
                {"key": "mind-map", "skill": "mind-map"},
                {"key": "review", "skill": "review"},
                {"key": "extra", "skill": "extra"},
            ],
        }
        record = self.store.create(workflow)
        self.assertEqual(record["stageOrder"], ["mind-map", "review", "extra"])

    def test_only_requirement_analysis_then_exit_persists_one_record(self) -> None:
        record = self._create()
        self.store.append_revision(
            record["recordId"],
            "requirement-analysis",
            {"scope": "demo"},
            skill_fingerprint="sha256:abc",
            skill_version="1.1.0",
        )
        # 进程退出后重新打开存储，仍是同一条记录
        reopened = RecordStore(self.runs_dir).load(record["recordId"])
        self.assertEqual(reopened["status"], "WAITING_HUMAN")
        self.assertEqual(len(RecordStore(self.runs_dir).list_records()), 1)

    def test_resume_and_continue_next_stage_in_same_record(self) -> None:
        record = self._create()
        record_id = record["recordId"]
        self.store.append_revision(
            record_id, "requirement-analysis", {"a": 1}, skill_fingerprint="sha256:a"
        )
        self.store.pause(record_id)
        self.assertEqual(self.store.load(record_id)["status"], "PAUSED")
        with self.assertRaisesRegex(RecordError, "PAUSED"):
            self.store.approve(record_id, "requirement-analysis")

        resumed = self.store.resume(record_id)
        self.assertEqual(resumed["status"], "WAITING_HUMAN")
        approved = self.store.approve(record_id, "requirement-analysis")
        self.assertEqual(approved["currentStageKey"], "test-point-generation")

        self.store.append_revision(
            record_id, "test-point-generation", {"b": 2}, skill_fingerprint="sha256:b"
        )
        done = self.store.approve(record_id, "test-point-generation")
        self.assertEqual(done["status"], "COMPLETED")
        self.assertIsNone(done["currentStageKey"])
        self.assertEqual(
            self.store.next_action(record_id),
            {"recordId": record_id, "status": "COMPLETED", "action": "DONE"},
        )

    def test_reject_appends_new_revision_and_keeps_old_one(self) -> None:
        record = self._create()
        record_id = record["recordId"]
        self.store.append_revision(
            record_id, "requirement-analysis", {"draft": 1}, skill_fingerprint="sha256:a"
        )
        self.store.reject(record_id, "requirement-analysis", reason="范围不完整")
        self.store.append_revision(
            record_id, "requirement-analysis", {"draft": 2}, skill_fingerprint="sha256:a"
        )

        first = self.store.load_revision(record_id, "requirement-analysis", "revision-0001")
        second = self.store.load_revision(record_id, "requirement-analysis", "revision-0002")
        self.assertEqual(first["payload"], {"draft": 1})
        self.assertEqual(second["payload"], {"draft": 2})
        revisions = self.store.load(record_id)["stages"]["requirement-analysis"]["revisions"]
        self.assertEqual(
            [item["decision"] for item in revisions], ["REJECTED", "PENDING"]
        )
        self.assertEqual(revisions[0]["decisionReason"], "范围不完整")

    def test_revision_files_are_never_overwritten(self) -> None:
        record = self._create()
        record_id = record["recordId"]
        self.store.append_revision(
            record_id, "requirement-analysis", {"draft": 1}, skill_fingerprint="sha256:a"
        )
        stage_dir = self.runs_dir / record_id / "stages" / "requirement-analysis"
        original = (stage_dir / "revision-0001.json").read_text(encoding="utf-8")
        self.store.reject(record_id, "requirement-analysis")
        self.store.append_revision(
            record_id, "requirement-analysis", {"draft": 2}, skill_fingerprint="sha256:a"
        )
        self.assertEqual(
            (stage_dir / "revision-0001.json").read_text(encoding="utf-8"), original
        )
        self.assertTrue((stage_dir / "revision-0002.json").is_file())

    def test_append_revision_rejects_wrong_stage(self) -> None:
        record = self._create()
        with self.assertRaisesRegex(RecordError, "当前阶段"):
            self.store.append_revision(
                record["recordId"],
                "test-point-generation",
                {"b": 1},
                skill_fingerprint="sha256:b",
            )

    def test_records_refuse_secrets(self) -> None:
        record = self._create()
        with self.assertRaisesRegex(RecordError, "敏感字段"):
            self.store.append_revision(
                record["recordId"],
                "requirement-analysis",
                {"token": "x"},
                skill_fingerprint="sha256:a",
            )
        with self.assertRaisesRegex(RecordError, "Access Token"):
            self.store.append_revision(
                record["recordId"],
                "requirement-analysis",
                {"note": "tw_ext_abcdef123456"},
                skill_fingerprint="sha256:a",
            )
        with self.assertRaises(RecordError):
            ensure_no_secrets({"nested": [{"api_key": "x"}]})

    def test_local_skill_changes_do_not_affect_history(self) -> None:
        with tempfile.TemporaryDirectory() as skill_temp:
            skill_dir = Path(skill_temp) / "requirement-analysis"
            skill_dir.mkdir()
            (skill_dir / "prompt.md").write_text("v1", encoding="utf-8")
            fingerprint_v1 = compute_directory_fingerprint(skill_dir)

            record = self._create()
            revision = self.store.append_revision(
                record["recordId"],
                "requirement-analysis",
                {"draft": 1},
                skill_fingerprint=fingerprint_v1,
                skill_version="1.1.0",
            )

            # 修改本地 Skill，指纹变化，但历史 Revision 保留旧指纹
            (skill_dir / "prompt.md").write_text("v2", encoding="utf-8")
            fingerprint_v2 = compute_directory_fingerprint(skill_dir)
            self.assertNotEqual(fingerprint_v1, fingerprint_v2)

            stored = self.store.load_revision(
                record["recordId"], "requirement-analysis", revision["revisionId"]
            )
            self.assertEqual(stored["skillFingerprint"], fingerprint_v1)

    def test_attach_reference_keeps_platform_ids_optional(self) -> None:
        record = self._create()
        updated = self.store.attach_reference(
            record["recordId"],
            "candidates",
            {"candidateId": "cand-1", "taskId": "task-1"},
        )
        self.assertEqual(
            updated["references"]["candidates"][0]["candidateId"], "cand-1"
        )

    def test_next_action_transitions(self) -> None:
        record = self._create()
        record_id = record["recordId"]
        self.assertEqual(self.store.next_action(record_id)["action"], "GENERATE")
        self.store.append_revision(
            record_id, "requirement-analysis", {"a": 1}, skill_fingerprint="sha256:a"
        )
        self.assertEqual(self.store.next_action(record_id)["action"], "HUMAN_DECISION")
        self.store.pause(record_id)
        self.assertEqual(self.store.next_action(record_id)["action"], "RESUME")


if __name__ == "__main__":
    unittest.main()
