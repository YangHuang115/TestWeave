# TestWeave 外接 Agent 客户端工作区（External Agent Workspace）

本目录包含 TestWeave「外接 Agent」的独立运行客户端 `run_agent.py`。它是一个**零第三方依赖**（仅用 Python 标准库）的 Gateway HTTP 客户端，可在任意环境、离线运行，通过 HTTP 对接本机 TestWeave Gateway。

> 外接 Agent 是「第二类客户端」：不是长期 Worker，不需要心跳、Lease、任务领取或在线状态；只能通过 HTTP API / MCP / CLI 调用 TestWeave，不能直接访问数据库或修改服务端文件。

## 前置条件

- 已按仓库根 `README.md` 本地启动 TestWeave（服务端 Gateway 默认监听 `http://127.0.0.1:8787`）。
- Python 3.12+（仅使用标准库，无需安装依赖）。

## 第一步：获取 Access Token

1. 启动后访问 Web 界面，进入目标项目，在「设置 / Access Token」生成**外接 Agent Token**（形如 `tw_ext_xxxxxxxxxxxx`）。
2. 复制配置模板并填写本地密钥：

   ```bash
   cp external_agent_workspace/.env.example external_agent_workspace/.env.local
   ```

   编辑 `external_agent_workspace/.env.local`：

   ```ini
   TESTWEAVE_AGENT_TOKEN=tw_ext_你的真实token
   TESTWEAVE_GATEWAY_URL=http://127.0.0.1:8787   # 与服务同机，默认回环地址即可
   ```

## 第二步：运行

直接启动（校验 Session 并打印可用操作）：

```bash
python external_agent_workspace/run_agent.py
```

带首句直接解析工作台任务：

```bash
python external_agent_workspace/run_agent.py "继续处理 TASK-000001 的测试点生成"
```

## 安全约束（重要）

- Gateway 的 `8787` 端口**仅绑定回环地址**（`127.0.0.1` / `::1`），拒绝绑定公网网卡（`0.0.0.0`）。因此外接 Agent 必须与 TestWeave 服务端**运行在同一台机器**上。
- Token 采用 `Authorization: Bearer tw_ext_xxxxxxxxxxxx` 鉴权；生效权限 = 授予权限 ∩ 项目角色允许权限，项目角色变更（如降级为 `VIEWER`）会即时缩减权限，无需重新颁发 Token。

## 协议速查（curl 示例）

```bash
# 校验 Session
curl http://127.0.0.1:8787/external/v1/session \
  -H "Authorization: Bearer tw_ext_你的token"

# 当前项目测试任务列表
curl http://127.0.0.1:8787/external/v1/tasks \
  -H "Authorization: Bearer tw_ext_你的token"

# 提交测试点候选
curl -X POST http://127.0.0.1:8787/external/v1/revision/candidates \
  -H "Authorization: Bearer tw_ext_你的token" \
  -H "Content-Type: application/json" \
  -d '{"capabilityId":"<CAPABILITY_ID>","artifactType":"test_point_set@1.0","payload":{"points":[{"title":"新测试点"}]},"summary":"External CLI Agent Submission"}'
```

## 目录内其他文件说明

- `AGENTS.md` / `CLAUDE.md`：外部 Agent 的操作指令，供 Agent 运行参考。
- `.testweave/`：**未随本仓库发布**。仅当你要用自有的 Claude Code / Codex / 通用 Agent 对接 Gateway 时才需要（适配器说明、客户端配置、结构化 Schema）；本基础客户端 `run_agent.py` 不依赖它。
- `.env.example`：配置模板（已发布）；`.env.local` 为本地密钥，**不要提交**。

## 相关阅读（仓库内部，未随公开版发布）

完整的「外接 Agent Client 开发者指南」（协议细节、Scope 字典、Python CLI SDK 用例）位于内部 `docs/project/M09-External-Agent-Client-Guide.md` 与 `docs/features/M13-Agent-Client-Dev-Starter-v0.1/`。公开版聚焦「开箱即用」；如需从零构建自有客户端，请参考内部仓库对应文档。
