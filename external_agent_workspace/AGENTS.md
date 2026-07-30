# Agent Instructions

<!-- TESTWEAVE:EXTERNAL-CLIENT:START -->
## TestWeave External Client

本工作区默认以**本地模式（local）**工作，连接 TestWeave 是可选操作。

### 三种模式

| 模式 | 何时使用 | Token | HTTP |
|------|---------|-------|------|
| `local`（默认） | 本地使用 Skill 生成/评审测试设计产物 | 不需要 | 禁止 |
| `connected` | 用户明确要求连接 TestWeave 读任务/需求、提交 Candidate | 需要 | 仅必要接口 |
| `share` | 作者确认 Skill 可用后，显式分享同步草稿 | 需要 `skill:sync` | 仅 sync-draft |

### Quick Start（本地模式，默认）

1. 直接从 `skills/<skill-id>/` 读取 `SKILL.md`、`prompt.md` 与输入输出 Schema，不需要 Token、注册、同步或发布。
2. 流程顺序由 `capabilities/ai-test-design/workflow.yaml` 定义（需求分析 → 测试点 → 测试用例 → 评审，每阶段人工确认）。
3. 用 `python run_agent.py --record-start ...` 创建本地链式记录，`--record-submit` 保存阶段产物（自动做输出 Schema 校验），`--record-approve` / `--record-reject` 处理人工确认，`--record-resume` 恢复中断的记录。记录保存在 `runs/`（已 gitignore）。
4. 本地模式下不得发起任何 HTTP 请求。

### 连接模式（仅用户明确选择时）

1. 读取 `.env.local` 获取 `TESTWEAVE_AGENT_TOKEN` 和 `TESTWEAVE_GATEWAY_URL`（缺省值见 `.env.example`；Gateway 与 TestWeave 主服务同进程同端口）。修改 `TESTWEAVE_GATEWAY_URL` 后运行 `python run_agent.py --init` 同步 `.testweave/` 适配器配置。
2. 调用 `GET /external/v1/tasks` 获取任务列表及关联需求全文。
3. 基于需求内容生成产物，通过 `POST /external/v1/revision/candidates` 提交候选。
4. 日常连接 Token 只需 `test_task.read` + `requirement.read` + `revision:candidate`；`workspace:spec` 仅在真实调用对应接口时需要；**不要**把 `skill:sync` 加入日常 Token。
5. 连接模式不会、也不应自动同步或发布 Skill。

### 分享模式（独立操作）

- 显式执行 `python run_agent.py --mode share --sync-skills <skill-id>`，调用 `POST /external/v1/skills/sync-draft`，只产生 `SYNCED_DRAFT`。
- 外接 Agent 不能发布；发布只能由具备 `agent.manage` 的授权 Web 用户在平台执行，发布版本是当前项目内的不可变快照。

### 连接配置

- Token 位于 `.env.local`，格式 `TESTWEAVE_AGENT_TOKEN=tw_ext_xxx`，仅 connected/share 模式读取。
- `.testweave/client/` 目录在本工作区不存在，无需尝试读取。

### API 路由决策（connected 模式）

| 场景 | 路径 | 备注 |
|------|------|------|
| 获取任务+需求全文 | `GET /external/v1/tasks` | 直接可用，无额外 scope 要求 |
| 获取单个任务详情 | `GET /external/v1/tasks/{taskId}` | 同上 |
| 工作台解析（需 scope） | `POST /external/v1/workbench/resolve` | 需要 `requirement.read` \| `test_task.read` |
| 分享同步草稿（share 模式） | `POST /external/v1/skills/sync-draft` | 需要 `skill:sync`，只产生 `SYNCED_DRAFT` |
| 提交候选产物 | `POST /external/v1/revision/candidates` | 可用 |
| 会话检查 | `GET /external/v1/session` | 可用，返回 scopes/project 信息 |

### 提交候选 (Candidate Submission)

**Artifact Type 必须带版本后缀：**
- `requirement_analysis@1.0` — 需求分析
- `test_point_set@1.0` — 测试点集
- `test_case_set@1.0` — 测试用例集

**请求体结构：**
```json
{
  "capabilityId": "1d9d6739-7fdc-4c8e-8337-4af959c566f2",
  "taskId": "<uuid>",
  "artifactType": "requirement_analysis@1.0",
  "payload": { ... },
  "summary": "简要描述",
  "autoPublish": false
}
```

**Schema 约束（已踩坑）：**
- `questions[].answer`：不能为 null，PENDING 时用空字符串 `""`。
- `questions[].status`：枚举值为 `PENDING` / `ANSWERED` / `ASSUMPTION_ACCEPTED` / `DEFERRED` / `OUT_OF_SCOPE`（无 OPEN、无 HUMAN_CONFIRMED）。
- `inferences[].decision`：`PENDING` / `ACCEPTED` / `REJECTED`。
- `evidence[].sourceType`：`REQUIREMENT` / `ATTACHMENT` / `HUMAN_DECISION`。
- `test_point_set@1.0` 逐点必填：`stableKey` / `scope` / `preconditions`(数组) / `coreAction` / `coreExpected` / `variables` / `testMethod` / `testMethodReason` / `risk` / `questionRefs` / `moduleRelationRefs` / `allowCaseGeneration`。
- 支持幂等提交：请求头 `Idempotency-Key: <unique-string>`。

### 行为规则

1. Default to local mode; never require or read a token before the mode is determined.
2. In local mode, never make HTTP requests; load skills directly from `skills/`.
3. Call TestWeave only through HTTP API, MCP, or CLI, and only in connected/share mode.
4. Never access the TestWeave database directly.
5. Never modify TestWeave server files.
6. Submit generated content as structured candidate results.
7. Do not approve or publish your own generated results; publication requires a Web user with `agent.manage`.
8. Do not treat `.testweave/output/` as a platform inbox.
9. On revision or context conflict, reload current state instead of overwriting.
10. Candidate submission must keep `autoPublish=false`.
11. For `NEEDS_SELECTION`, `BLOCKED`, or `NOT_FOUND` responses, show content and wait for user.
12. Never auto-sync or auto-publish skills in connected mode; sharing is an explicit `--mode share` operation.
13. Local skill use does not require registration, sync, or publication.
<!-- TESTWEAVE:EXTERNAL-CLIENT:END -->
