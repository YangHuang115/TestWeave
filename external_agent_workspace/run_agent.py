#!/usr/bin/env python3
"""
TestWeave External Agent Client 独立运行脚本范例
本脚本完全零第三方依赖（仅使用 Python 标准库），可在任意路径和离线环境独立运行。

传入首句时只展示 Gateway 返回的工作台内容：
    python run_agent.py "继续处理 TASK-000001 的测试点生成"
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TASK_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


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


def main() -> None:
    first_message = " ".join(sys.argv[1:]).strip()

    # 1. 优先尝试从本地环境文件加载 Token
    workspace_dir = Path(__file__).resolve().parent
    env_vars = load_env_file(workspace_dir / ".env.local")
    if not env_vars:
        env_vars = load_env_file(workspace_dir / ".env")

    token = os.getenv("TESTWEAVE_AGENT_TOKEN") or env_vars.get("TESTWEAVE_AGENT_TOKEN")
    gateway_url = (
        os.getenv("TESTWEAVE_GATEWAY_URL")
        or env_vars.get("TESTWEAVE_GATEWAY_URL")
        or "http://127.0.0.1:8787"
    )

    if not token or token == "tw_agent_replace_me":
        print("⚠️ 未检测到有效的 TESTWEAVE_AGENT_TOKEN 环境变量。")
        print(
            "💡 请在 Web 界面获取 Access Token 后将其写入 external_agent_workspace/.env.local 文件:"
        )
        print("   TESTWEAVE_AGENT_TOKEN='tw_ext_xxxxxxxxxxxx'")
        print("   TESTWEAVE_GATEWAY_URL='http://127.0.0.1:8787'")
        sys.exit(1)

    client = StandaloneExternalAgentClient(gateway_url=gateway_url, token=token)

    if first_message:
        try:
            print(render_workbench(client.resolve_workbench(first_message)))
        except Exception as exc:
            print(f"工作台加载失败：{exc}")
            sys.exit(1)
        return

    print("=== 启动 TestWeave External Agent Client ===")
    print(f"📡 连接 Gateway 地址: {gateway_url}")

    # 2. 会话可用性检查
    try:
        session = client.check_session()
        print("✅ Gateway Session 鉴权通过:")
        print(
            f"   用户: {session.get('userName', 'unknown')} (项目角色: {session.get('userRole', 'unknown')})"
        )
        print(f"   项目 ID: {session.get('projectId', 'unknown')}")
        print(f"   授权 Scopes: {session.get('effectiveScopes', [])}")
    except Exception as e:
        print(f"❌ Session 鉴权失败: {e}")
        sys.exit(1)

    print("\n🎉 External Agent Client 初始化就绪！")
    print("-------------------------------------------------------------")
    print("💡 接下来您可以运行如下操作进行 API 功能校验：")
    print("   1) 列出当前项目测试任务: client.list_tasks()")
    print("   2) 提交测试点候选: client.submit_candidate(...)")
    print("-------------------------------------------------------------")


if __name__ == "__main__":
    main()
