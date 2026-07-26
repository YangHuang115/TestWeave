#!/usr/bin/env python3
"""本地链式记录存储（runs/<record-id>/）。

只使用 Python 标准库。负责 AI 测试设计等多阶段能力在本地模式下的
链式记录：创建、恢复、追加阶段 Revision、人工确认/拒绝、暂停、查询
和推进下一阶段。

不变量：
- record.json 原子写入（临时文件 + os.replace）。
- Revision 文件一旦写入不再覆盖；重新生成只追加新 Revision。
- 每个 Revision 保存生成时的 Skill 包 fingerprint，本地 Skill 后续
  修改不影响历史记录。
- 记录中不允许出现 Token、密码或密钥。
- 阶段列表来自创建记录时冻结的 Workflow 定义，不写死阶段数量。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECORD_SCHEMA_VERSION = "1.0"

# 记录状态
STATUS_ACTIVE = "ACTIVE"
STATUS_WAITING_HUMAN = "WAITING_HUMAN"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
RECORD_STATUSES = {
    STATUS_ACTIVE,
    STATUS_WAITING_HUMAN,
    STATUS_PAUSED,
    STATUS_COMPLETED,
}

# 阶段状态
STAGE_PENDING = "PENDING"
STAGE_WAITING_HUMAN = "WAITING_HUMAN"
STAGE_APPROVED = "APPROVED"
STAGE_REJECTED = "REJECTED"

# Revision 决策
DECISION_PENDING = "PENDING"
DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"

_SECRET_KEY_PATTERN = re.compile(
    r"^(token|access[_-]?token|password|secret|api[_-]?key|authorization)$",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(r"tw_(ext|agent)_[0-9A-Za-z]{4,}")


class RecordError(ValueError):
    """记录操作的业务错误（可直接展示给用户）。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def compute_directory_fingerprint(directory: Path) -> str:
    """计算目录内容 sha256 指纹（排序后的相对路径 + 文件字节）。"""
    directory = Path(directory)
    if not directory.is_dir():
        raise RecordError(f"目录不存在: {directory}")
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def ensure_no_secrets(value: Any, path: str = "$") -> None:
    """拒绝把 Token、密码或密钥写入本地记录。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY_PATTERN.match(str(key)):
                raise RecordError(f"记录禁止包含敏感字段: {path}.{key}")
            ensure_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            ensure_no_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if _SECRET_VALUE_PATTERN.search(value):
            raise RecordError(f"记录禁止包含疑似 Access Token 的值: {path}")


def _atomic_write_json(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)


class RecordStore:
    """基于 runs/ 目录的本地链式记录存储。"""

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)

    # ---------- 基础读写 ----------

    def _record_path(self, record_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", record_id):
            raise RecordError(f"非法 recordId: {record_id}")
        return self.runs_dir / record_id / "record.json"

    def load(self, record_id: str) -> dict:
        path = self._record_path(record_id)
        if not path.is_file():
            raise RecordError(f"记录不存在: {record_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, record: dict) -> None:
        record["updatedAt"] = utc_now()
        _atomic_write_json(self._record_path(record["recordId"]), record)

    def list_records(self) -> list[dict]:
        results = []
        if not self.runs_dir.is_dir():
            return results
        for entry in sorted(self.runs_dir.iterdir()):
            record_file = entry / "record.json"
            if entry.is_dir() and record_file.is_file():
                try:
                    results.append(json.loads(record_file.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return results

    # ---------- 生命周期 ----------

    def create(
        self,
        workflow: dict,
        title: str = "",
        initial_input: dict | None = None,
        references: dict | None = None,
    ) -> dict:
        """按 Workflow 定义冻结阶段序列并创建新记录。"""
        stages = workflow.get("stages") or []
        if not stages:
            raise RecordError("Workflow 未定义任何阶段，无法创建记录")
        stage_keys = [stage.get("key") for stage in stages]
        if len(set(stage_keys)) != len(stage_keys) or not all(stage_keys):
            raise RecordError("Workflow 阶段 key 缺失或重复")
        ensure_no_secrets(initial_input or {})
        ensure_no_secrets(references or {})

        now = utc_now()
        record = {
            "schemaVersion": RECORD_SCHEMA_VERSION,
            "recordId": str(uuid.uuid4()),
            "capabilityId": workflow.get("capability", "unknown"),
            "workflowVersion": workflow.get("version", "unknown"),
            "allowPauseResume": bool(workflow.get("allow_pause_resume", True)),
            "title": title,
            "status": STATUS_ACTIVE,
            "createdAt": now,
            "updatedAt": now,
            "initialInput": initial_input or {},
            # 引用只作为可选关联保存，不作为平台写入依据
            "references": references or {},
            "stageOrder": stage_keys,
            "currentStageKey": stage_keys[0],
            "stages": {
                stage["key"]: {
                    "stageKey": stage["key"],
                    "skillId": stage.get("skill", stage["key"]),
                    "inputFrom": stage.get("input_from", "initial"),
                    "humanConfirmation": bool(stage.get("human_confirmation", True)),
                    "status": STAGE_PENDING,
                    "revisions": [],
                }
                for stage in stages
            },
        }
        self._save(record)
        return record

    def resume(self, record_id: str) -> dict:
        """恢复记录：PAUSED 记录回到中断前的等待态，其余状态保持不变。"""
        record = self.load(record_id)
        if record["status"] == STATUS_COMPLETED:
            return record
        if record["status"] == STATUS_PAUSED:
            record["status"] = self._derive_running_status(record)
            self._save(record)
        return record

    def pause(self, record_id: str) -> dict:
        record = self.load(record_id)
        if not record.get("allowPauseResume", True):
            raise RecordError("该 Workflow 不允许暂停")
        if record["status"] == STATUS_COMPLETED:
            raise RecordError("记录已完成，无法暂停")
        record["status"] = STATUS_PAUSED
        self._save(record)
        return record

    def _derive_running_status(self, record: dict) -> str:
        stage = record["stages"].get(record.get("currentStageKey") or "")
        if stage and stage["status"] == STAGE_WAITING_HUMAN:
            return STATUS_WAITING_HUMAN
        return STATUS_ACTIVE

    # ---------- 阶段 Revision ----------

    def append_revision(
        self,
        record_id: str,
        stage_key: str,
        payload: dict,
        skill_fingerprint: str,
        skill_version: str = "unknown",
        upstream_revision: str | None = None,
    ) -> dict:
        """为当前阶段追加一个新的 Revision；旧 Revision 永不覆盖。"""
        record = self.load(record_id)
        if record["status"] == STATUS_COMPLETED:
            raise RecordError("记录已完成，不能追加 Revision")
        if record["status"] == STATUS_PAUSED:
            raise RecordError("记录处于 PAUSED，请先恢复记录")
        if stage_key != record.get("currentStageKey"):
            raise RecordError(
                f"只能向当前阶段 {record.get('currentStageKey')} 追加 Revision，"
                f"收到 {stage_key}"
            )
        stage = record["stages"][stage_key]
        ensure_no_secrets(payload)

        revision_no = len(stage["revisions"]) + 1
        revision_id = f"revision-{revision_no:04d}"
        revision_path = (
            self.runs_dir / record_id / "stages" / stage_key / f"{revision_id}.json"
        )
        if revision_path.exists():
            raise RecordError(f"Revision 已存在，禁止覆盖: {revision_path.name}")

        now = utc_now()
        revision_doc = {
            "recordId": record_id,
            "stageKey": stage_key,
            "revisionId": revision_id,
            "createdAt": now,
            "skillId": stage["skillId"],
            "skillVersion": skill_version,
            "skillFingerprint": skill_fingerprint,
            "upstreamRevision": upstream_revision,
            "payload": payload,
        }
        _atomic_write_json(revision_path, revision_doc)

        stage["revisions"].append(
            {
                "revisionId": revision_id,
                "createdAt": now,
                "skillVersion": skill_version,
                "skillFingerprint": skill_fingerprint,
                "decision": DECISION_PENDING,
                "decisionAt": None,
                "decisionReason": None,
            }
        )
        if stage["humanConfirmation"]:
            stage["status"] = STAGE_WAITING_HUMAN
            record["status"] = STATUS_WAITING_HUMAN
        else:
            stage["status"] = STAGE_APPROVED
            stage["revisions"][-1]["decision"] = DECISION_APPROVED
            stage["revisions"][-1]["decisionAt"] = now
            self._advance(record, stage_key)
        self._save(record)
        return revision_doc

    def load_revision(self, record_id: str, stage_key: str, revision_id: str) -> dict:
        path = (
            self.runs_dir / record_id / "stages" / stage_key / f"{revision_id}.json"
        )
        if not path.is_file():
            raise RecordError(f"Revision 不存在: {stage_key}/{revision_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _latest_pending_revision(self, stage: dict) -> dict:
        for revision in reversed(stage["revisions"]):
            if revision["decision"] == DECISION_PENDING:
                return revision
        raise RecordError(f"阶段 {stage['stageKey']} 没有待确认的 Revision")

    def approve(self, record_id: str, stage_key: str) -> dict:
        """人工确认当前阶段最新 Revision 并推进到下一阶段。"""
        record = self.load(record_id)
        if record["status"] == STATUS_PAUSED:
            raise RecordError("记录处于 PAUSED，请先恢复记录")
        if stage_key != record.get("currentStageKey"):
            raise RecordError(f"只能确认当前阶段 {record.get('currentStageKey')}")
        stage = record["stages"][stage_key]
        revision = self._latest_pending_revision(stage)
        revision["decision"] = DECISION_APPROVED
        revision["decisionAt"] = utc_now()
        stage["status"] = STAGE_APPROVED
        self._advance(record, stage_key)
        self._save(record)
        return record

    def reject(self, record_id: str, stage_key: str, reason: str = "") -> dict:
        """人工拒绝当前阶段最新 Revision；阶段回到待重新生成。"""
        record = self.load(record_id)
        if record["status"] == STATUS_PAUSED:
            raise RecordError("记录处于 PAUSED，请先恢复记录")
        if stage_key != record.get("currentStageKey"):
            raise RecordError(f"只能拒绝当前阶段 {record.get('currentStageKey')}")
        stage = record["stages"][stage_key]
        revision = self._latest_pending_revision(stage)
        revision["decision"] = DECISION_REJECTED
        revision["decisionAt"] = utc_now()
        revision["decisionReason"] = reason
        stage["status"] = STAGE_REJECTED
        record["status"] = STATUS_ACTIVE
        self._save(record)
        return record

    def _advance(self, record: dict, stage_key: str) -> None:
        order = record["stageOrder"]
        index = order.index(stage_key)
        if index + 1 < len(order):
            record["currentStageKey"] = order[index + 1]
            record["status"] = STATUS_ACTIVE
        else:
            record["currentStageKey"] = None
            record["status"] = STATUS_COMPLETED

    def attach_reference(self, record_id: str, kind: str, reference: dict) -> dict:
        """把 Candidate/Revision/Task ID 等平台对象作为可选引用保存。"""
        ensure_no_secrets(reference)
        record = self.load(record_id)
        record.setdefault("references", {}).setdefault(kind, []).append(
            {**reference, "attachedAt": utc_now()}
        )
        self._save(record)
        return record

    def next_action(self, record_id: str) -> dict:
        """返回记录下一步该做什么（供 CLI/Agent 展示）。"""
        record = self.load(record_id)
        status = record["status"]
        stage_key = record.get("currentStageKey")
        if status == STATUS_COMPLETED or stage_key is None:
            return {"recordId": record_id, "status": status, "action": "DONE"}
        stage = record["stages"][stage_key]
        if status == STATUS_PAUSED:
            action = "RESUME"
        elif stage["status"] == STAGE_WAITING_HUMAN:
            action = "HUMAN_DECISION"
        else:
            action = "GENERATE"
        return {
            "recordId": record_id,
            "status": status,
            "action": action,
            "stageKey": stage_key,
            "skillId": stage["skillId"],
            "inputFrom": stage["inputFrom"],
        }
