#!/usr/bin/env python3
"""
TestWeave External Agent Client 独立运行脚本（本地优先、连接可选、分享发布独立）。
本脚本完全零第三方依赖（仅使用 Python 标准库），可在任意路径和离线环境独立运行。

三种显式模式：

- ``--mode local``（默认）：不需要 Token、不发起任何 HTTP 请求；直接从
  ``skills/`` 加载 Skill，按 ``capabilities/ai-test-design/workflow.yaml``
  驱动本地链式记录（runs/）。
- ``--mode connected``：用户明确选择连接 TestWeave 时才读取 Token；只做
  任务/需求读取和 Candidate 提交，不自动同步、不发布 Skill。
- ``--mode share``：作者确认 Skill 可用后的独立分享操作；显式调用
  ``POST /external/v1/skills/sync-draft``，只产生 SYNCED_DRAFT，发布由
  具备 ``agent.manage`` 的授权 Web 用户在平台完成。

示例：

    python run_agent.py --list-skills
    python run_agent.py --record-start --title "登录需求" --input spec.md
    python run_agent.py --mode connected "继续处理 TASK-000001 的测试点生成"
    python run_agent.py --mode share --sync-skills
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 支持从任意路径加载本脚本（如服务端回归测试通过文件路径 import），
# 确保工作区内的 scripts/ 包可被解析。
_WORKSPACE_ROOT = str(Path(__file__).resolve().parent)
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

from scripts.skill_records import (
    RecordError,
    RecordStore,
    compute_directory_fingerprint,
)

TASK_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

# Skill 文件契约中必须存在的根文件（与服务器 Manifest 协议保持一致）
REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "manifest.yaml",
    "prompt.md",
    "input.schema.json",
    "output.schema.json",
    "CHANGELOG.md",
)

DEFAULT_CAPABILITY = "ai-test-design"


def load_env_file(filepath: Path) -> dict:
    """加载本地精简的 .env/.env.local 键值对"""
    env_vars = {}
    if filepath.is_file():
        try:
            with filepath.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
        except Exception:
            pass
    return env_vars


# ---------------------------------------------------------------------------
# 精简 YAML 子集解析（映射、嵌套、标量列表、映射列表；拒绝 Tab/锚点/别名/重复键）
# ---------------------------------------------------------------------------


class SimpleYamlError(ValueError):
    """本地 YAML 子集解析错误。"""


def _strip_yaml_comment(line: str) -> str:
    result: list[str] = []
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            result.append(char)
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            result.append(char)
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        else:
            result.append(char)
    return "".join(result).rstrip()


def _yaml_tokens(text: str) -> list[tuple[int, str, int]]:
    tokens = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise SimpleYamlError(f"第 {lineno} 行禁止使用 Tab 缩进")
        line = _strip_yaml_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        tokens.append((indent, line.strip(), lineno))
    return tokens


def _parse_yaml_scalar(text: str, lineno: int):
    if text.startswith("&") or text.startswith("*"):
        raise SimpleYamlError(f"第 {lineno} 行禁止使用 YAML 锚点/别名")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if text in ("null", "~", "Null"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _parse_yaml_map(tokens, index: int, indent: int):
    result: dict = {}
    while index < len(tokens):
        tok_indent, content, lineno = tokens[index]
        if tok_indent < indent:
            break
        if tok_indent > indent:
            raise SimpleYamlError(f"第 {lineno} 行缩进错误")
        if content == "-" or content.startswith("- "):
            break
        key_text, sep, rest = content.partition(":")
        if not sep:
            raise SimpleYamlError(f"第 {lineno} 行缺少键值分隔符")
        key = _parse_yaml_scalar(key_text.strip(), lineno)
        if not isinstance(key, str) or not key:
            raise SimpleYamlError(f"第 {lineno} 行键名非法")
        if key in result:
            raise SimpleYamlError(f"第 {lineno} 行存在重复键: {key}")
        rest = rest.strip()
        index += 1
        if rest == "":
            if index < len(tokens) and tokens[index][0] > indent:
                value, index = _parse_yaml_block(tokens, index, tokens[index][0])
            elif (
                index < len(tokens)
                and tokens[index][0] == indent
                and (tokens[index][1] == "-" or tokens[index][1].startswith("- "))
            ):
                value, index = _parse_yaml_list(tokens, index, indent)
            else:
                value = None
        elif rest == "[]":
            value = []
        elif rest == "{}":
            value = {}
        else:
            value = _parse_yaml_scalar(rest, lineno)
        result[key] = value
    return result, index


def _parse_yaml_list(tokens, index: int, indent: int):
    result: list = []
    while index < len(tokens):
        tok_indent, content, lineno = tokens[index]
        if tok_indent != indent or not (content == "-" or content.startswith("- ")):
            break
        rest = content[1:].strip()
        index += 1
        if not rest:
            if index < len(tokens) and tokens[index][0] > tok_indent:
                value, index = _parse_yaml_block(tokens, index, tokens[index][0])
            else:
                value = None
            result.append(value)
            continue
        if ":" in rest and not rest.startswith(("'", '"')):
            key_text, _, val_text = rest.partition(":")
            key = _parse_yaml_scalar(key_text.strip(), lineno)
            if not isinstance(key, str) or not key:
                raise SimpleYamlError(f"第 {lineno} 行列表项键名非法")
            val_text = val_text.strip()
            if val_text == "[]":
                first_value = []
            elif val_text == "{}":
                first_value = {}
            elif val_text == "":
                first_value = None
            else:
                first_value = _parse_yaml_scalar(val_text, lineno)
            item = {key: first_value}
            if index < len(tokens) and tokens[index][0] > tok_indent:
                sub, index = _parse_yaml_map(tokens, index, tokens[index][0])
                for sub_key, sub_value in sub.items():
                    if sub_key in item:
                        raise SimpleYamlError(f"第 {lineno} 行列表项重复键: {sub_key}")
                    item[sub_key] = sub_value
            result.append(item)
        else:
            result.append(_parse_yaml_scalar(rest, lineno))
    return result, index


def _parse_yaml_block(tokens, index: int, indent: int):
    if index < len(tokens) and (
        tokens[index][1] == "-" or tokens[index][1].startswith("- ")
    ):
        return _parse_yaml_list(tokens, index, indent)
    return _parse_yaml_map(tokens, index, indent)


def parse_simple_yaml(text: str) -> dict:
    """解析本工作区使用的 YAML 子集；不支持也不需要完整 YAML。"""
    tokens = _yaml_tokens(text)
    if not tokens:
        return {}
    value, index = _parse_yaml_block(tokens, 0, tokens[0][0])
    if index != len(tokens):
        raise SimpleYamlError(f"第 {tokens[index][2]} 行无法解析")
    return value if isinstance(value, dict) else {"items": value}


# ---------------------------------------------------------------------------
# 精简 JSON Schema 校验（覆盖四个 Skill Schema 实际使用的关键字子集）
# ---------------------------------------------------------------------------

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve_schema_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"只支持文档内 $ref: {ref}")
    node = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"无法解析 $ref: {ref}")
        node = node[part]
    if not isinstance(node, dict):
        raise ValueError(f"$ref 目标不是 Schema 对象: {ref}")
    return node


def validate_json_schema(instance, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """按 Schema 子集校验实例，返回错误列表（空列表表示通过）。"""
    if root is None:
        root = schema
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    if "$ref" in schema:
        return validate_json_schema(
            instance, _resolve_schema_ref(root, schema["$ref"]), root, path
        )

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS.get(t, lambda _v: True)(instance) for t in types):
            errors.append(f"{path}: 期望类型 {expected}")
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: 值不在枚举范围 {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 值必须等于 {schema['const']!r}")

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(f"{path}: 长度不足 minLength={min_length}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            errors.append(f"{path}: 小于 minimum={minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and instance > maximum:
            errors.append(f"{path}: 大于 maximum={maximum}")

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(instance) < min_items:
            errors.append(f"{path}: 数组长度不足 minItems={min_items}")
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(
                    validate_json_schema(item, items_schema, root, f"{path}[{index}]")
                )

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 {key}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(
                    validate_json_schema(value, properties[key], root, f"{path}.{key}")
                )
        additional = schema.get("additionalProperties")
        if additional is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: 不允许未声明字段 {key}")
        elif isinstance(additional, dict):
            for key, value in instance.items():
                if key not in properties:
                    errors.extend(
                        validate_json_schema(value, additional, root, f"{path}.{key}")
                    )
    return errors


# ---------------------------------------------------------------------------
# Skill 与 Workflow 加载（本地模式核心：无需注册、同步或发布）
# ---------------------------------------------------------------------------


class SkillLoadError(ValueError):
    """Skill 包结构或契约错误。"""


def load_skill(skill_dir: Path) -> dict:
    """加载并结构校验一个本地 Skill 包。"""
    skill_dir = Path(skill_dir)
    if not skill_dir.is_dir() or skill_dir.is_symlink():
        raise SkillLoadError(f"Skill 目录不存在或不是普通目录: {skill_dir}")
    for filename in REQUIRED_SKILL_FILES:
        if not (skill_dir / filename).is_file():
            raise SkillLoadError(f"{skill_dir.name}: 缺少必需文件 {filename}")

    try:
        manifest = parse_simple_yaml(
            (skill_dir / "manifest.yaml").read_text(encoding="utf-8")
        )
    except SimpleYamlError as exc:
        raise SkillLoadError(f"{skill_dir.name}: manifest.yaml 解析失败: {exc}") from exc

    meta = manifest.get("skill")
    if not isinstance(meta, dict):
        raise SkillLoadError(f"{skill_dir.name}: manifest.yaml 缺少 skill 段")
    skill_id = meta.get("id")
    if skill_id != skill_dir.name or not SKILL_ID_PATTERN.match(str(skill_id)):
        raise SkillLoadError(
            f"{skill_dir.name}: manifest skill.id 必须等于目录名且为 kebab-case"
        )
    version = str(meta.get("version", ""))
    if not SEMVER_PATTERN.match(version):
        raise SkillLoadError(f"{skill_dir.name}: skill.version 必须是语义版本号")
    for field in ("prompt", "input_schema", "output_schema"):
        declared = meta.get(field)
        if not declared or not (skill_dir / str(declared)).is_file():
            raise SkillLoadError(f"{skill_dir.name}: manifest 声明的 {field} 文件不存在")

    schemas = {}
    for side, filename in (
        ("input", str(meta["input_schema"])),
        ("output", str(meta["output_schema"])),
    ):
        try:
            schema = json.loads((skill_dir / filename).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SkillLoadError(f"{skill_dir.name}: {filename} 不是合法 JSON") from exc
        if not isinstance(schema, dict):
            raise SkillLoadError(f"{skill_dir.name}: {filename} 必须是 JSON 对象")
        schemas[side] = schema

    return {
        "id": skill_id,
        "version": version,
        "name": meta.get("name", skill_id),
        "dir": skill_dir,
        "manifest": manifest,
        "required_permissions": meta.get("required_permissions") or [],
        "input_schema": schemas["input"],
        "output_schema": schemas["output"],
        "fingerprint": compute_directory_fingerprint(skill_dir),
    }


def discover_skills(skills_dir: Path) -> tuple[dict, dict]:
    """发现 skills/ 下全部 Skill；返回 (成功加载, 错误信息)。"""
    skills: dict[str, dict] = {}
    errors: dict[str, str] = {}
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return skills, {"skills": f"Skill 目录不存在: {skills_dir}"}
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        try:
            skills[entry.name] = load_skill(entry)
        except SkillLoadError as exc:
            errors[entry.name] = str(exc)
    return skills, errors


def load_workflow(capability_dir: Path) -> dict:
    """加载文件驱动的能力流程定义（workflow.yaml）。"""
    workflow_path = Path(capability_dir) / "workflow.yaml"
    if not workflow_path.is_file():
        raise SkillLoadError(f"流程定义不存在: {workflow_path}")
    workflow = parse_simple_yaml(workflow_path.read_text(encoding="utf-8"))
    stages = workflow.get("stages")
    if not isinstance(stages, list) or not stages:
        raise SkillLoadError("workflow.yaml 必须声明非空 stages 列表")
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or not stage.get("key") or not stage.get("skill"):
            raise SkillLoadError("workflow.yaml 每个阶段必须声明 key 和 skill")
        if stage["key"] in seen:
            raise SkillLoadError(f"workflow.yaml 阶段 key 重复: {stage['key']}")
        seen.add(stage["key"])
    return workflow


class StandaloneExternalAgentClient:
    """独立轻量 Gateway HTTP 客户端 (无需安装 testweave 库)"""

    def __init__(self, gateway_url: str = "http://127.0.0.1:8787", token: str = ""):
        self.gateway_url = gateway_url.rstrip("/")
        self.token = token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        headers_extra: dict | None = None,
    ) -> dict:
        url = f"{self.gateway_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if headers_extra:
            headers.update(headers_extra)

        data = json.dumps(payload).encode("utf-8") if payload else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                # 尝试解析响应
                res_data = json.loads(body) if body else {}
                # 在响应回显里增加 Header 信息便于调试
                if "Idempotency-Replay" in resp.headers:
                    res_data["_idempotency_replay"] = True
                return res_data
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message", err_body)
                code = err_json.get("code", "UNKNOWN_ERROR")
            except Exception:
                msg = err_body
                code = "UNKNOWN_ERROR"
            raise RuntimeError(f"HTTP {err.code} ({code}): {msg}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(
                f"网络连接失败: {err.reason}\n提示: 宿主机 127.0.0.1:8787 端口可能未启动 Gateway 服务，或被本地沙箱拦截。"
            ) from err

    def check_session(self) -> dict:
        return self._request("GET", "/external/v1/session")

    def list_tasks(self) -> dict:
        """获取项目测试任务列表 (包含关联需求简要)"""
        return self._request("GET", "/external/v1/tasks")

    def get_task_detail(self, task_id: str) -> dict:
        """查询特定任务详情 (自动包含关联的需求文档正文与附件元数据)"""
        return self._request("GET", f"/external/v1/tasks/{task_id}")

    def get_requirement_detail(self, requirement_id: str) -> dict:
        """读取特定需求详情及正文文档内容"""
        return self._request("GET", f"/external/v1/requirements/{requirement_id}")

    def resolve_workbench(self, message: str) -> dict:
        """将用户首句解析为只读工作台和唯一安全执行入口"""
        return self._request(
            "POST",
            "/external/v1/workbench/resolve",
            payload={"message": message},
        )

    def execute_workbench_entry(self, workbench: dict) -> dict:
        """执行 READY 工作台返回的安全任务上下文读取入口"""
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

    def submit_candidate(
        self,
        artifact_type: str,
        payload: dict,
        capability_id: str | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        summary: str = "",
    ) -> dict:
        """
        提交生成的 Candidate 候选结果到 Gateway。
        支持幂等性传输控制（Idempotency-Key）；固定保持候选状态。
        """
        req_data = {
            "capabilityId": capability_id,
            "taskId": task_id,
            "artifactType": artifact_type,
            "payload": payload,
            "summary": summary,
            "autoPublish": False,
        }

        headers_extra = {}
        if idempotency_key:
            headers_extra["Idempotency-Key"] = idempotency_key

        return self._request(
            "POST",
            "/external/v1/revision/candidates",
            payload=req_data,
            headers_extra=headers_extra,
        )

    def sync_skill_directory(self, skill_dir: Path) -> dict:
        """显式同步一个本地 Skill 目录；拒绝符号链接和非 UTF-8 文件。"""
        skill_dir = skill_dir.absolute()
        if not skill_dir.is_dir() or skill_dir.is_symlink():
            raise ValueError(f"Skill 目录不存在或不是普通目录: {skill_dir}")

        files = []
        for path in sorted(skill_dir.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Skill 包禁止包含符号链接: {path.relative_to(skill_dir)}")
            if not path.is_file():
                continue
            relative_path = path.relative_to(skill_dir).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Skill 包只允许 UTF-8 文本文件: {relative_path}") from exc
            files.append({"path": relative_path, "content": content})

        if not files:
            raise ValueError(f"Skill 目录没有可同步文件: {skill_dir}")
        return self._request(
            "POST",
            "/external/v1/skills/sync-draft",
            payload={"files": files},
        )


def render_workbench(workbench: dict) -> str:
    """把首轮握手响应渲染为只包含业务内容的中文工作台。"""
    status = workbench.get("status", "NOT_FOUND")
    intent = workbench.get("intent") or {}
    project = workbench.get("project") or {}
    content = workbench.get("workbench") or {}
    version = content.get("version") or {}
    task = content.get("task") or {}
    requirement = content.get("requirement") or {}
    requirements = content.get("requirements") or []

    lines = [
        "# 当前工作台",
        "",
        f"- 你的目标：{intent.get('message', '未提供')}",
        f"- 当前项目：{project.get('name', '未定位')}",
        f"- 当前版本：{version.get('name') or version.get('key') or '未定位'}",
        f"- 当前任务：{task.get('key', '未定位')} {task.get('title', '')}".rstrip(),
        f"- 当前阶段：{intent.get('stage', '未定位')}",
        f"- 当前状态：{status}",
    ]

    if requirement:
        lines.append(
            f"- 当前需求：{requirement.get('key', '未定位')} "
            f"{requirement.get('title', '')}".rstrip()
        )
    for item in requirements:
        lines.append(
            f"- 关联需求：{item.get('key', '未定位')} {item.get('title', '')}".rstrip()
        )

    blockers = workbench.get("blockers") or []
    for blocker in blockers:
        lines.append(f"- 当前阻塞：{blocker.get('message', '未知阻塞')}")

    candidates = workbench.get("candidates") or []
    if candidates:
        lines.extend(["", "# 待选择入口", ""])
        for item in candidates:
            lines.append(
                f"- {item.get('key', '未知')} {item.get('title', '')} "
                f"（{item.get('status', 'UNKNOWN')}）".rstrip()
            )

    entry = workbench.get("entryPoint")
    if isinstance(entry, dict):
        lines.extend(
            [
                "",
                "# 直接执行入口",
                "",
                f"- 执行动作：{entry.get('action', '未定位')}",
                f"- 任务入口：{entry.get('path', '未定位')}",
                f"- 目标阶段：{entry.get('stage', '未定位')}",
                f"- 产物类型：{entry.get('artifactType', '未定位')}",
                "",
                "回复“继续”即可直接读取任务上下文。",
            ]
        )
    elif status == "NOT_FOUND":
        lines.extend(["", "未找到与首句对应的工作对象，请补充任务或需求编号。"])
    elif status == "NEEDS_SELECTION":
        lines.extend(["", "请回复要继续的任务编号。"])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 本地模式命令（不需要 Token，不发起任何 HTTP 请求）
# ---------------------------------------------------------------------------


class WorkspacePaths:
    """按工作区根目录组织本地路径。"""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)
        self.skills_dir = self.workspace_dir / "skills"
        self.capabilities_dir = self.workspace_dir / "capabilities"
        self.runs_dir = self.workspace_dir / "runs"

    def capability_dir(self, capability: str) -> Path:
        return self.capabilities_dir / capability

    def record_store(self) -> RecordStore:
        return RecordStore(self.runs_dir)


def read_initial_input(raw: str) -> dict:
    """支持文本、JSON、Markdown 和本地文件作为初始输入。"""
    path = Path(raw)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix == ".json":
            return {"type": "json", "source": str(path), "content": json.loads(text)}
        if suffix in (".md", ".markdown"):
            return {"type": "markdown", "source": str(path), "content": text}
        return {"type": "text", "source": str(path), "content": text}
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        try:
            return {"type": "json", "source": "inline", "content": json.loads(stripped)}
        except json.JSONDecodeError:
            pass
    return {"type": "text", "source": "inline", "content": raw}


def _load_json_file(path_text: str) -> dict:
    path = Path(path_text)
    if not path.is_file():
        raise SkillLoadError(f"文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SkillLoadError(f"文件必须是 JSON 对象: {path}")
    return data


def cmd_list_skills(paths: WorkspacePaths) -> int:
    skills, errors = discover_skills(paths.skills_dir)
    print("# 本地 Skill（无需注册、同步或发布即可使用）")
    for skill in skills.values():
        print(
            f"- {skill['id']} v{skill['version']} ✅ 结构校验通过 "
            f"({skill['fingerprint'][:19]}…)"
        )
    for name, message in errors.items():
        print(f"- {name} ❌ {message}")
    return 1 if errors else 0


def cmd_show_workflow(paths: WorkspacePaths, capability: str) -> int:
    workflow = load_workflow(paths.capability_dir(capability))
    print(f"# 能力流程：{workflow.get('capability')} v{workflow.get('version')}")
    print(f"- 允许暂停/恢复：{workflow.get('allow_pause_resume', True)}")
    for stage in workflow["stages"]:
        gate = "→ 人工确认" if stage.get("human_confirmation", True) else ""
        print(
            f"- {stage['key']}（Skill: {stage['skill']}，输入来自: "
            f"{stage.get('input_from', 'initial')}）{gate}"
        )
    return 0


def cmd_validate_payload(paths: WorkspacePaths, skill_id: str, side: str, file: str) -> int:
    skill = load_skill(paths.skills_dir / skill_id)
    schema = skill["input_schema"] if side == "input" else skill["output_schema"]
    payload = _load_json_file(file)
    errors = validate_json_schema(payload, schema)
    if errors:
        print(f"❌ {skill_id} {side} Schema 校验失败：")
        for item in errors:
            print(f"  - {item}")
        return 1
    print(f"✅ {skill_id} {side} Schema 校验通过")
    return 0


def _print_record_summary(record: dict) -> None:
    print(f"- 记录: {record['recordId']}")
    print(f"- 标题: {record.get('title') or '(未命名)'}")
    print(f"- 状态: {record['status']}")
    print(f"- 当前阶段: {record.get('currentStageKey') or '(已完成)'}")
    for key in record["stageOrder"]:
        stage = record["stages"][key]
        revisions = ", ".join(
            f"{item['revisionId']}={item['decision']}" for item in stage["revisions"]
        )
        print(f"  - {key}: {stage['status']} [{revisions or '无 Revision'}]")


def cmd_record_start(paths: WorkspacePaths, capability: str, title: str, input_arg: str | None) -> int:
    workflow = load_workflow(paths.capability_dir(capability))
    skills, errors = discover_skills(paths.skills_dir)
    missing = [
        stage["skill"]
        for stage in workflow["stages"]
        if stage["skill"] not in skills
    ]
    if missing:
        print(f"❌ 流程引用的 Skill 未通过本地加载: {missing}; 错误: {errors}")
        return 1
    initial_input = read_initial_input(input_arg) if input_arg else {}
    record = paths.record_store().create(
        workflow, title=title, initial_input=initial_input
    )
    print("✅ 已创建本地链式记录")
    _print_record_summary(record)
    print(
        f"下一步：由 Agent 按 skills/{record['stages'][record['currentStageKey']]['skillId']}/"
        "SKILL.md 生成输出后，用 --record-submit 提交。"
    )
    return 0


def cmd_record_submit(paths: WorkspacePaths, record_id: str, stage_key: str, output_file: str) -> int:
    store = paths.record_store()
    record = store.load(record_id)
    stage = record["stages"].get(stage_key)
    if stage is None:
        print(f"❌ 记录中不存在阶段: {stage_key}")
        return 1
    skill = load_skill(paths.skills_dir / stage["skillId"])
    payload = _load_json_file(output_file)
    schema_errors = validate_json_schema(payload, skill["output_schema"])
    if schema_errors:
        print(f"❌ 输出未通过 {skill['id']} output Schema 校验：")
        for item in schema_errors:
            print(f"  - {item}")
        return 1

    upstream_revision = None
    input_from = stage.get("inputFrom", "initial")
    if input_from != "initial" and input_from in record["stages"]:
        upstream = record["stages"][input_from]
        approved = [
            item for item in upstream["revisions"] if item["decision"] == "APPROVED"
        ]
        if approved:
            upstream_revision = f"{input_from}/{approved[-1]['revisionId']}"

    revision = store.append_revision(
        record_id,
        stage_key,
        payload,
        skill_fingerprint=skill["fingerprint"],
        skill_version=skill["version"],
        upstream_revision=upstream_revision,
    )
    print(f"✅ 已保存 {stage_key}/{revision['revisionId']}（等待人工确认）")
    return 0


def cmd_record_show(paths: WorkspacePaths, record_id: str) -> int:
    record = paths.record_store().load(record_id)
    _print_record_summary(record)
    return 0


def cmd_record_list(paths: WorkspacePaths) -> int:
    records = paths.record_store().list_records()
    if not records:
        print("暂无本地记录（runs/ 为空）")
        return 0
    for record in records:
        print(
            f"- {record['recordId']} [{record['status']}] "
            f"{record.get('title') or '(未命名)'} → "
            f"{record.get('currentStageKey') or '已完成'}"
        )
    return 0


def cmd_record_next(paths: WorkspacePaths, record_id: str) -> int:
    action = paths.record_store().next_action(record_id)
    print(json.dumps(action, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 模式解析与主入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_agent.py",
        description="TestWeave 外接 Agent 客户端：本地优先、连接可选、分享发布独立。",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "connected", "share"],
        help="运行模式；缺省为 local（首句消息保持 connected 兼容行为）",
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(Path(__file__).resolve().parent),
        help="工作区根目录（默认脚本所在目录；主要用于测试隔离）",
    )
    parser.add_argument("message", nargs="*", help="连接模式的首句消息")

    local = parser.add_argument_group("local 模式（默认，无需 Token）")
    local.add_argument("--list-skills", action="store_true", help="发现并结构校验本地 Skill")
    local.add_argument("--show-workflow", action="store_true", help="显示文件驱动的流程定义")
    local.add_argument("--capability", default=DEFAULT_CAPABILITY, help="能力 ID")
    local.add_argument("--validate-skill", metavar="SKILL_ID", help="校验单个 Skill 包结构")
    local.add_argument(
        "--validate-payload",
        nargs=3,
        metavar=("SKILL_ID", "SIDE", "FILE"),
        help="按 Skill 的 input/output Schema 校验 JSON 文件",
    )
    local.add_argument("--record-start", action="store_true", help="创建本地链式记录")
    local.add_argument("--title", default="", help="记录标题")
    local.add_argument("--input", dest="initial_input", help="初始输入（文本 / JSON / Markdown / 文件路径）")
    local.add_argument("--record-list", action="store_true", help="列出本地记录")
    local.add_argument("--record-show", metavar="RECORD_ID", help="查看记录详情")
    local.add_argument("--record-resume", metavar="RECORD_ID", help="恢复记录")
    local.add_argument("--record-pause", metavar="RECORD_ID", help="暂停记录")
    local.add_argument("--record-submit", metavar="RECORD_ID", help="向当前阶段追加 Revision")
    local.add_argument("--stage", help="阶段 key（配合 --record-submit/approve/reject）")
    local.add_argument("--output", help="阶段输出 JSON 文件（配合 --record-submit）")
    local.add_argument("--record-approve", metavar="RECORD_ID", help="人工确认当前阶段")
    local.add_argument("--record-reject", metavar="RECORD_ID", help="人工拒绝当前阶段")
    local.add_argument("--reason", default="", help="拒绝原因")
    local.add_argument("--record-next", metavar="RECORD_ID", help="查询下一步动作")

    connected = parser.add_argument_group("connected 模式（显式连接 TestWeave）")
    connected.add_argument("--list-tasks", action="store_true", help="读取项目任务列表")
    connected.add_argument("--task", metavar="TASK_ID", help="读取任务详情")
    connected.add_argument("--requirement", metavar="REQUIREMENT_ID", help="读取需求详情")
    connected.add_argument("--submit-candidate", action="store_true", help="提交 Candidate")
    connected.add_argument("--artifact-type", help="Candidate artifactType（如 test_point_set@1.0）")
    connected.add_argument("--payload-file", help="Candidate payload JSON 文件")
    connected.add_argument("--task-id", help="Candidate 关联任务 ID")
    connected.add_argument("--capability-id", help="Candidate 关联 Capability ID")
    connected.add_argument("--summary", default="", help="Candidate 摘要")
    connected.add_argument("--idempotency-key", help="幂等键")
    connected.add_argument("--record", help="把返回的 Candidate ID 挂到本地记录（可选引用）")

    share = parser.add_argument_group("share 模式（作者确认后的独立分享操作）")
    share.add_argument(
        "--sync-skills",
        nargs="*",
        metavar="SKILL_ID",
        default=None,
        help="显式同步 Skill 草稿（等价于 --mode share；仅创建 SYNCED_DRAFT）",
    )
    return parser


def resolve_mode(args: argparse.Namespace) -> str:
    """先根据参数确定模式，再决定是否读取 Token；绝不先检查 Token。"""
    if args.mode:
        return args.mode
    if args.sync_skills is not None:
        return "share"  # 兼容别名：--sync-skills 即显式分享
    if (
        args.message
        or args.list_tasks
        or args.task
        or args.requirement
        or args.submit_candidate
    ):
        return "connected"
    return "local"


def load_token_and_gateway(workspace_dir: Path) -> tuple[str, str]:
    env_vars = load_env_file(workspace_dir / ".env.local")
    if not env_vars:
        env_vars = load_env_file(workspace_dir / ".env")
    token = os.getenv("TESTWEAVE_AGENT_TOKEN") or env_vars.get("TESTWEAVE_AGENT_TOKEN") or ""
    gateway_url = (
        os.getenv("TESTWEAVE_GATEWAY_URL")
        or env_vars.get("TESTWEAVE_GATEWAY_URL")
        or "http://127.0.0.1:8787"
    )
    return token, gateway_url


def run_local(args: argparse.Namespace, paths: WorkspacePaths) -> int:
    """local 模式入口：本函数内禁止创建 Gateway 客户端或发起 HTTP 请求。"""
    if args.sync_skills is not None:
        print("❌ local 模式不能同步 Skill；分享请使用 --mode share --sync-skills")
        return 1
    if args.message or args.list_tasks or args.task or args.requirement or args.submit_candidate:
        print("❌ local 模式不访问 TestWeave；请使用 --mode connected")
        return 1
    try:
        store = paths.record_store()
        if args.list_skills:
            return cmd_list_skills(paths)
        if args.show_workflow:
            return cmd_show_workflow(paths, args.capability)
        if args.validate_skill:
            skill = load_skill(paths.skills_dir / args.validate_skill)
            print(f"✅ {skill['id']} v{skill['version']} 结构校验通过")
            return 0
        if args.validate_payload:
            skill_id, side, file = args.validate_payload
            if side not in ("input", "output"):
                print("❌ SIDE 只能是 input 或 output")
                return 1
            return cmd_validate_payload(paths, skill_id, side, file)
        if args.record_start:
            return cmd_record_start(paths, args.capability, args.title, args.initial_input)
        if args.record_list:
            return cmd_record_list(paths)
        if args.record_show:
            return cmd_record_show(paths, args.record_show)
        if args.record_resume:
            record = store.resume(args.record_resume)
            print("✅ 记录已恢复")
            _print_record_summary(record)
            return 0
        if args.record_pause:
            store.pause(args.record_pause)
            print("✅ 记录已暂停（PAUSED）")
            return 0
        if args.record_submit:
            if not args.stage or not args.output:
                print("❌ --record-submit 需要 --stage 和 --output")
                return 1
            return cmd_record_submit(paths, args.record_submit, args.stage, args.output)
        if args.record_approve:
            if not args.stage:
                print("❌ --record-approve 需要 --stage")
                return 1
            record = store.approve(args.record_approve, args.stage)
            print("✅ 已人工确认")
            _print_record_summary(record)
            return 0
        if args.record_reject:
            if not args.stage:
                print("❌ --record-reject 需要 --stage")
                return 1
            record = store.reject(args.record_reject, args.stage, args.reason)
            print("✅ 已人工拒绝，请重新生成新 Revision")
            _print_record_summary(record)
            return 0
        if args.record_next:
            return cmd_record_next(paths, args.record_next)

        # 无参数：展示本地工作区状态（无需 Token 即可启动）
        print("=== TestWeave 外接 Agent 工作区（local 模式，无需 Token） ===")
        skills, errors = discover_skills(paths.skills_dir)
        print(f"- 本地 Skill：{len(skills)} 个可用" + (f"，{len(errors)} 个异常" if errors else ""))
        try:
            workflow = load_workflow(paths.capability_dir(args.capability))
            print(f"- 默认流程：{' → '.join(s['key'] for s in workflow['stages'])}")
        except SkillLoadError as exc:
            print(f"- 默认流程：不可用（{exc}）")
        records = store.list_records()
        print(f"- 本地记录：{len(records)} 条（runs/）")
        print("提示：--list-skills 查看 Skill；--record-start 开始链式记录；"
              "--mode connected 连接 TestWeave；--mode share 分享 Skill 草稿。")
        return 0
    except (SkillLoadError, RecordError, SimpleYamlError, json.JSONDecodeError) as exc:
        print(f"❌ {exc}")
        return 1


def run_connected(args: argparse.Namespace, paths: WorkspacePaths, client: "StandaloneExternalAgentClient") -> int:
    """connected 模式：只读取任务/需求并提交 Candidate；绝不自动同步或发布 Skill。"""
    if args.sync_skills is not None:
        print("❌ connected 模式不同步 Skill；分享请使用 --mode share --sync-skills")
        return 1
    try:
        if args.message:
            print(render_workbench(client.resolve_workbench(" ".join(args.message).strip())))
            return 0
        if args.list_tasks:
            print(json.dumps(client.list_tasks(), ensure_ascii=False, indent=2))
            return 0
        if args.task:
            print(json.dumps(client.get_task_detail(args.task), ensure_ascii=False, indent=2))
            return 0
        if args.requirement:
            print(
                json.dumps(
                    client.get_requirement_detail(args.requirement),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.submit_candidate:
            if not args.artifact_type or not args.payload_file:
                print("❌ --submit-candidate 需要 --artifact-type 和 --payload-file")
                return 1
            payload = _load_json_file(args.payload_file)
            result = client.submit_candidate(
                artifact_type=args.artifact_type,
                payload=payload,
                capability_id=args.capability_id,
                task_id=args.task_id,
                idempotency_key=args.idempotency_key,
                summary=args.summary,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            candidate_id = result.get("candidateId") or result.get("id")
            if args.record and candidate_id:
                paths.record_store().attach_reference(
                    args.record,
                    "candidates",
                    {
                        "candidateId": candidate_id,
                        "stageKey": args.stage,
                        "artifactType": args.artifact_type,
                        "taskId": args.task_id,
                    },
                )
                print(f"✅ Candidate 引用已挂到本地记录 {args.record}")
            return 0

        # 无业务参数：会话可用性检查
        session = client.check_session()
        print("✅ Gateway Session 鉴权通过:")
        print(
            f"   用户: {session.get('userName', 'unknown')} (项目角色: {session.get('userRole', 'unknown')})"
        )
        print(f"   项目 ID: {session.get('projectId', 'unknown')}")
        print(f"   授权 Scopes: {session.get('effectiveScopes', [])}")
        print("提示：日常连接 Token 只需要 test_task.read / requirement.read / revision:candidate。")
        return 0
    except (RuntimeError, ValueError, RecordError, SkillLoadError) as exc:
        print(f"❌ {exc}")
        return 1


def run_share(args: argparse.Namespace, paths: WorkspacePaths, client: "StandaloneExternalAgentClient") -> int:
    """share 模式：显式同步 Skill 草稿；只产生 SYNCED_DRAFT，发布由平台授权用户执行。"""
    names = args.sync_skills or []
    try:
        if names:
            skill_dirs = [paths.skills_dir / name for name in names]
        else:
            skill_dirs = sorted(
                path
                for path in paths.skills_dir.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
        if not skill_dirs:
            raise ValueError(f"未找到 Skill 目录: {paths.skills_dir}")
        for skill_dir in skill_dirs:
            load_skill(skill_dir)  # 分享前先本地结构校验
            result = client.sync_skill_directory(skill_dir)
            print(
                f"✅ {skill_dir.name}: {result.get('status', 'UNKNOWN')} "
                f"{result.get('version', '')}".rstrip()
            )
        print("说明：同步只创建 SYNCED_DRAFT；发布需具备项目 agent.manage 权限的用户在平台执行。")
        return 0
    except (RuntimeError, ValueError, SkillLoadError) as exc:
        print(f"Skill 同步失败：{exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = WorkspacePaths(Path(args.workspace_dir))
    mode = resolve_mode(args)

    if mode == "local":
        return run_local(args, paths)

    # 只有 connected/share 模式才读取 Token
    token, gateway_url = load_token_and_gateway(paths.workspace_dir)
    if not token or token == "tw_agent_replace_me":
        print(f"⚠️ {mode} 模式需要有效的 TESTWEAVE_AGENT_TOKEN。")
        print("💡 请在 Web 界面获取 Access Token 后写入 external_agent_workspace/.env.local：")
        print("   TESTWEAVE_AGENT_TOKEN='tw_ext_xxxxxxxxxxxx'")
        print("   TESTWEAVE_GATEWAY_URL='http://127.0.0.1:8787'")
        if mode == "connected":
            print("   日常连接 Token 权限：test_task.read、requirement.read、revision:candidate。")
        else:
            print("   分享 Token 权限：skill:sync（不要加入日常使用 Token）。")
        print("   本地使用不需要 Token：直接运行 python run_agent.py（local 模式）。")
        return 1

    client = StandaloneExternalAgentClient(gateway_url=gateway_url, token=token)
    if mode == "share":
        return run_share(args, paths, client)
    return run_connected(args, paths, client)


if __name__ == "__main__":
    sys.exit(main())
