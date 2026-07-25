# Agent Instructions

<!-- TESTWEAVE:EXTERNAL-CLIENT:START -->
## TestWeave External Client

This workspace is connected to TestWeave.

### Quick Start (最快路径)

1. 读取 `.env.local` 获取 `TESTWEAVE_AGENT_TOKEN` 和 `TESTWEAVE_GATEWAY_URL`（默认 `http://127.0.0.1:8787`）。
2. 调用 `GET /external/v1/tasks` 获取任务列表及关联需求全文。
3. 基于需求内容生成产物，通过 `POST /external/v1/revision/candidates` 提交候选。

### 连接配置

- Token 位于 `.env.local`，格式 `TESTWEAVE_AGENT_TOKEN=tw_ext_xxx`。
- `.testweave/client/` 目录在本工作区不存在，无需尝试读取。
- 当前 token scopes 为 `revision:candidate` + `workspace:spec`，不含 `requirement.read` / `test_task.read`。

### API 路由决策

| 场景 | 路径 | 备注 |
|------|------|------|
| 获取任务+需求全文 | `GET /external/v1/tasks` | 直接可用，无额外 scope 要求 |
| 获取单个任务详情 | `GET /external/v1/tasks/{taskId}` | 同上 |
| 工作台解析（需 scope） | `POST /external/v1/workbench/resolve` | 需要 `requirement.read` \| `test_task.read`，当前 token **不可用**，跳过 |
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

1. Call TestWeave only through HTTP API, MCP, or CLI.
2. Never access the TestWeave database directly.
3. Never modify TestWeave server files.
4. Submit generated content as structured candidate results.
5. Do not approve or publish your own generated results.
6. Do not treat `.testweave/output/` as a platform inbox.
7. On revision or context conflict, reload current state instead of overwriting.
8. Candidate submission must keep `autoPublish=false`.
9. For `NEEDS_SELECTION`, `BLOCKED`, or `NOT_FOUND` responses, show content and wait for user.
<!-- TESTWEAVE:EXTERNAL-CLIENT:END -->
