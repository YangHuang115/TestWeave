# TestWeave 外接 Agent 客户端工作区（External Agent Workspace）

本目录是 TestWeave AI 测试设计能力的**本地优先**工作区：四个 Skill 以真实文件存在，本地即可发现、加载、校验并驱动完整的「需求分析 → 测试点 → 测试用例 → 用例评审」链式流程；连接 TestWeave 是可选操作，分享（同步草稿）与发布是相互独立的显式操作。

`run_agent.py` 是**零第三方依赖**（仅 Python 标准库）的独立客户端，可在任意环境、离线运行。

> 外接 Agent 是「第二类客户端」：不是长期 Worker，不需要心跳、Lease、任务领取或在线状态；只能通过 HTTP API / MCP / CLI 调用 TestWeave，不能直接访问数据库或修改服务端文件。

## 三种模式一览

| 模式 | 用途 | 是否需要 Token | 所需权限 |
| --- | --- | --- | --- |
| `--mode local`（默认） | 本地使用 Skill、驱动链式记录 | **不需要** | 无 |
| `--mode connected` | 显式连接 TestWeave 读任务/需求、提交 Candidate | 需要 | `test_task.read`、`requirement.read`、`revision:candidate` |
| `--mode share` | 作者确认后独立分享 Skill 草稿 | 需要 | `skill:sync`（不要加入日常 Token） |

规则：

- local 模式不需要 Token、不需要服务器注册 Skill、不需要 `skill:sync`、不需要发布，也**不发起任何 HTTP 请求**。
- connected 模式不会自动同步或发布 Skill；`workspace:spec` 只有真实调用对应接口时才需要。
- share 模式只调用 `POST /external/v1/skills/sync-draft`，只产生 `SYNCED_DRAFT`；发布只能由具备项目 `agent.manage` 权限的 Web 用户在平台执行，范围是当前项目，发布后的版本是不可变快照。

## 本地模式（开箱即用，无需 Token）

前置条件只有 Python 3.12+。

```bash
# 查看工作区状态（Skill、流程、记录）
python external_agent_workspace/run_agent.py

# 发现并结构校验四个 Skill
python external_agent_workspace/run_agent.py --list-skills

# 查看文件驱动的流程定义（capabilities/ai-test-design/workflow.yaml）
python external_agent_workspace/run_agent.py --show-workflow
```

### 本地链式记录（runs/）

一次完整的 AI 测试设计属于同一条记录，跨阶段、可中断、可恢复：

```bash
# 1. 创建记录（输入支持文本、JSON、Markdown 或本地文件路径）
python external_agent_workspace/run_agent.py --record-start --title "登录需求" --input spec.md

# 2. Agent 按 skills/requirement-analysis/SKILL.md 生成输出后提交（自动 Schema 校验）
python external_agent_workspace/run_agent.py --record-submit <recordId> \
  --stage requirement-analysis --output analysis.json

# 3. 人工确认或拒绝（拒绝后重新生成会追加新 Revision，旧 Revision 保留）
python external_agent_workspace/run_agent.py --record-approve <recordId> --stage requirement-analysis
python external_agent_workspace/run_agent.py --record-reject <recordId> --stage test-point-generation --reason "覆盖不足"

# 4. 中断后随时恢复，查询下一步动作
python external_agent_workspace/run_agent.py --record-resume <recordId>
python external_agent_workspace/run_agent.py --record-next <recordId>

# 其他：--record-list / --record-show <recordId> / --record-pause <recordId>
```

记录状态：`ACTIVE`、`WAITING_HUMAN`、`PAUSED`、`COMPLETED`。每个 Revision 保存生成时的 Skill 包指纹；本地 Skill 后续修改不影响历史记录。`runs/` 只存在于本地且已加入 `.gitignore`，其中不允许写入 Token、密码或密钥。

阶段顺序、使用的 Skill、上游输入和人工确认点由 `capabilities/ai-test-design/workflow.yaml` 声明，不硬编码在 Python 或服务器中；未来加入脑图等新 Skill 时只需增加一个阶段条目。

## 连接模式（可选：读取 TestWeave 数据、提交 Candidate）

只有用户明确选择「连接 TestWeave」时才需要 Token：

1. 按仓库根 `README.md` 本地启动 TestWeave（Gateway 默认监听 `http://127.0.0.1:8787`）。
2. 在 Web 界面「设置 / Access Token」生成外接 Agent Token，日常连接只勾选 `test_task.read`、`requirement.read`、`revision:candidate`（**不要**包含 `skill:sync`）。
3. 写入本地配置：

   ```bash
   cp external_agent_workspace/.env.example external_agent_workspace/.env.local
   # 编辑 .env.local：
   # TESTWEAVE_AGENT_TOKEN=tw_ext_你的真实token
   # TESTWEAVE_GATEWAY_URL=http://127.0.0.1:8787
   ```

```bash
# 会话检查 / 首句解析工作台
python external_agent_workspace/run_agent.py --mode connected
python external_agent_workspace/run_agent.py --mode connected "继续处理 TASK-000001 的测试点生成"

# 读取任务与需求
python external_agent_workspace/run_agent.py --mode connected --list-tasks
python external_agent_workspace/run_agent.py --mode connected --task <taskId>
python external_agent_workspace/run_agent.py --mode connected --requirement <requirementId>

# 提交 Candidate（固定 autoPublish=false；可选把 Candidate ID 挂到本地记录作引用）
python external_agent_workspace/run_agent.py --mode connected --submit-candidate \
  --artifact-type test_point_set@1.0 --payload-file points.json \
  --task-id <taskId> --record <recordId> --stage test-point-generation
```

连接模式不能自动同步 Skill，也不能发布 Skill。本地链式记录不强制写入平台 AI Design Record；Candidate ID、Revision ID、Task ID 只作为可选引用保存在记录的 `references` 中。

## 分享模式（独立操作：同步 Skill 草稿）

分享是作者确认 Skill 可用之后的独立操作，使用单独的 `skill:sync` Token：

```bash
# 同步全部或指定 Skill（先本地结构校验，再调用 POST /external/v1/skills/sync-draft）
python external_agent_workspace/run_agent.py --mode share --sync-skills
python external_agent_workspace/run_agent.py --mode share --sync-skills requirement-analysis

# 兼容别名（等价于 --mode share --sync-skills）
python external_agent_workspace/run_agent.py --sync-skills
```

同步只创建 `SYNCED_DRAFT` 版本，外接 Agent 不能发布。发布前必须通过 Manifest 校验、输入输出 Schema 校验、路径/文件类型/符号链接等安全校验，并由具备项目 `agent.manage` 权限的用户明确确认后在平台执行；固定模型评测可以执行并展示结果，v1 不作为发布硬阻断。四个 Skill 都发布后，平台 AI 测试设计工作台新建记录才会绑定它们（缺少时返回 `AI_TEST_DESIGN_SKILLS_NOT_READY`，该错误不影响 local 和 connected 外接模式）。

## 四个可编辑 Skill

四个 Skill 的唯一可编辑源位于当前目录的 `skills/`：

| 目录 | 职责 |
| --- | --- |
| `skills/requirement-analysis/` | 需求分析 |
| `skills/test-point-generation/` | 测试点生成 |
| `skills/test-case-generation/` | 测试用例生成 |
| `skills/test-case-review/` | 测试用例评审 |

每个目录中的 `SKILL.md` 是 Agent 发现入口（含三种模式的使用说明），`prompt.md` 是 TestWeave Runtime 使用的模型指令，`manifest.yaml` 和两个 JSON Schema 是服务器注册契约。修改已同步版本时必须先提升 `manifest.yaml` 中的版本号并更新 `CHANGELOG.md`，不能用同一版本覆盖旧内容。

`.agents/skills/`、`.claude/skills/` 和 `.agent/skills/` 只包含指向上述目录的相对软链接，因此 Codex、Claude Code 和兼容 Agent 读取的是同一份源文件。

## 安全约束（重要）

- Gateway 的 `8787` 端口**仅绑定回环地址**（`127.0.0.1` / `::1`），拒绝绑定公网网卡（`0.0.0.0`）。因此外接 Agent 必须与 TestWeave 服务端**运行在同一台机器**上。
- Token 采用 `Authorization: Bearer tw_ext_xxxxxxxxxxxx` 鉴权；生效权限 = 授予权限 ∩ 项目角色允许权限，项目角色变更（如降级为 `VIEWER`）会即时缩减权限，无需重新颁发 Token。
- 按最小权限拆分 Token：日常连接 Token 不包含 `skill:sync`；`skill:sync` 只放在显式分享时使用的 Token 中。
- `.env.local`、`runs/`、`*.token`、`*.secret` 均已加入 `.gitignore`，不会被提交。

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

# 同步单个 Skill 草稿（Token 需要 skill:sync；仅分享时使用）
curl -X POST http://127.0.0.1:8787/external/v1/skills/sync-draft \
  -H "Authorization: Bearer tw_ext_你的token" \
  -H "Content-Type: application/json" \
  -d '{"files":[{"path":"manifest.yaml","content":"..."}]}'
```

## 目录内其他文件说明

- `AGENTS.md` / `CLAUDE.md`：外部 Agent 的操作指令，供 Agent 运行参考。
- `skills/`：四个可见、可编辑、可版本化的 AI 测试设计 Skill 源文件。
- `capabilities/ai-test-design/`：文件驱动的能力流程定义（`manifest.yaml` + `workflow.yaml`）。
- `scripts/skill_records.py`：本地链式记录存储实现（原子写入、Revision 不可覆盖）。
- `runs/`：本地链式记录数据（不提交、不上传）。
- `.agents/skills/`、`.claude/skills/`、`.agent/skills/`：指向 `skills/` 的激活链接，不是副本。
- `.testweave/`：**未随本仓库发布**。仅当你要用自有的 Claude Code / Codex / 通用 Agent 对接 Gateway 时才需要（适配器说明、客户端配置、结构化 Schema）；本基础客户端 `run_agent.py` 不依赖它。
- `.env.example`：配置模板（已发布）；`.env.local` 为本地密钥，**不要提交**。仅 connected / share 模式需要。

## 相关阅读（仓库内部，未随公开版发布）

完整的「外接 Agent Client 开发者指南」（协议细节、Scope 字典、Python CLI SDK 用例）位于内部 `docs/project/M09-External-Agent-Client-Guide.md` 与 `docs/features/M13-Agent-Client-Dev-Starter-v0.1/`。公开版聚焦「开箱即用」；如需从零构建自有客户端，请参考内部仓库对应文档。
