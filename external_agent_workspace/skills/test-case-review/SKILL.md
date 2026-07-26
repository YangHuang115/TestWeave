---
name: test-case-review
description: 评审 TestWeave 候选测试用例的可执行性、追踪性、覆盖和重复问题；当需要字段级问题与修订建议时使用。
---

# TestWeave 测试用例评审

评审已确认进入评审阶段的候选用例，输出可定位到字段的发现和修订请求。

## 运行模式

本 Skill 本地优先，三种模式相互独立：

- **local 模式（默认，无需 Token）**：Agent Host 直接从本目录发现并加载本 Skill，不需要服务器注册、同步（`skill:sync`）或发布，也不调用 Gateway。上游输入是本地链式记录中已人工确认的 `test-case-generation` 阶段 Revision；输出通过 `output.schema.json` 校验后用 `python run_agent.py --record-submit <recordId> --stage test-case-review --output <file.json>` 存入本地记录（runs/），等待人工确认。
- **connected 模式（显式连接 TestWeave）**：仅当用户明确选择连接时才使用 Token（权限 `test_task.read`、`requirement.read`、`revision:candidate`），通过 `python run_agent.py --mode connected --list-tasks` / `--task <id>` 读取任务与需求；评审结果以 Candidate 提交：`python run_agent.py --mode connected --submit-candidate --artifact-type test_case_review_report@1.0 --payload-file <file.json>`，固定 `autoPublish=false`。connected 模式不会自动同步或发布 Skill。
- **share 模式（独立分享操作）**：作者确认 Skill 可用后，显式执行 `python run_agent.py --mode share --sync-skills test-case-review`（Token 需 `skill:sync`），只创建 SYNCED_DRAFT；发布由具备项目 `agent.manage` 权限的 Web 用户在平台执行，范围仅限当前项目。

## 执行流程

1. local 模式从本地链式记录读取已确认的候选用例 Revision；connected 模式通过 TestWeave Gateway 读取目标记录、候选用例及可用上游证据，不直接访问数据库。
2. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
3. 上游链路完整时使用 `TRACEABLE`；只有用例本体时使用 `INTRINSIC`，不得伪造覆盖率。
4. 对每个问题给出准确 `caseRef`、`fieldPath`、证据引用、严重度和可执行建议。
5. 校验 JSON 后，local 模式用 `--record-submit` 存入本地记录等待人工确认；connected 模式通过 Gateway 提交评审候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 只评审，不直接重写测试用例。
- 不把建议自动应用为修订，也不替用户接受或拒绝发现。
- 不确认、发布或绕过人工评审门禁。
- 缺少上游证据时不得输出虚假的规则或测试点覆盖结论。
- 不把密钥、令牌或敏感原文写入输出。

本地使用不需要注册、同步和发布；只有平台 AI 测试设计工作台调用时，才要求把当前版本显式同步（share 模式）并由授权用户发布为不可变快照。
