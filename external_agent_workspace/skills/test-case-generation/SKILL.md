---
name: test-case-generation
description: 根据已人工确认且允许继续的 TestWeave 测试点生成结构化候选测试用例；当需要形成可执行步骤、数据和预期时使用。
---

# TestWeave 测试用例生成

把已确认测试点转换为可执行、可追踪、可评审的测试用例候选稿。

## 运行模式

本 Skill 本地优先，三种模式相互独立：

- **local 模式（默认，无需 Token）**：Agent Host 直接从本目录发现并加载本 Skill，不需要服务器注册、同步（`skill:sync`）或发布，也不调用 Gateway。上游输入是本地链式记录中已人工确认的 `test-point-generation` 阶段 Revision；输出通过 `output.schema.json` 校验后用 `python run_agent.py --record-submit <recordId> --stage test-case-generation --output <file.json>` 存入本地记录（runs/），等待人工确认。
- **connected 模式（显式连接 TestWeave）**：仅当用户明确选择连接时才使用 Token（权限 `test_task.read`、`requirement.read`、`revision:candidate`），通过 `python run_agent.py --mode connected --list-tasks` / `--task <id>` 读取任务与需求；生成结果以 Candidate 提交：`python run_agent.py --mode connected --submit-candidate --artifact-type test_case_set@1.0 --payload-file <file.json>`，固定 `autoPublish=false`。connected 模式不会自动同步或发布 Skill。
- **share 模式（独立分享操作）**：作者确认 Skill 可用后，显式执行 `python run_agent.py --mode share --sync-skills test-case-generation`（Token 需 `skill:sync`），只创建 SYNCED_DRAFT；发布由具备项目 `agent.manage` 权限的 Web 用户在平台执行，范围仅限当前项目。

## 执行流程

1. local 模式从本地链式记录读取已确认的测试点 Revision；connected 模式通过 TestWeave Gateway 读取目标记录和已确认的测试点修订，不直接访问数据库。
2. 只处理 `allowCaseGeneration=true` 的已确认测试点；否则停止。
3. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
4. 为每条用例指定唯一主测试点引用，并写出前置条件、测试数据、步骤、核心预期、观察点和清理动作。
5. 校验 JSON 后，local 模式用 `--record-submit` 存入本地记录等待人工确认；connected 模式通过 Gateway 提交候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 不使用未确认测试点，也不绕过 `allowCaseGeneration`。
- 不编造账号、环境、接口或业务规则。
- 不确认、发布或直接覆盖正式测试用例。
- 不在本阶段给出最终评审结论。
- 不自行修订上游需求分析或测试点。

本地使用不需要注册、同步和发布；只有平台 AI 测试设计工作台调用时，才要求把当前版本显式同步（share 模式）并由授权用户发布为不可变快照。
