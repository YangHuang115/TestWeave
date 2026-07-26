---
name: test-point-generation
description: 根据已人工确认的 TestWeave 需求分析生成可追踪、可评审的结构化测试点；当需求分析已经通过 Human Gate 时使用。
---

# TestWeave 测试点生成

把已确认的完整需求分析转换为测试点候选稿，并保留规则、问题和模块关系的追踪链路。

## 运行模式

本 Skill 本地优先，三种模式相互独立：

- **local 模式（默认，无需 Token）**：Agent Host 直接从本目录发现并加载本 Skill，不需要服务器注册、同步（`skill:sync`）或发布，也不调用 Gateway。上游输入是本地链式记录中已人工确认的 `requirement-analysis` 阶段 Revision；输出通过 `output.schema.json` 校验后用 `python run_agent.py --record-submit <recordId> --stage test-point-generation --output <file.json>` 存入本地记录（runs/），等待人工确认。
- **connected 模式（显式连接 TestWeave）**：仅当用户明确选择连接时才使用 Token（权限 `test_task.read`、`requirement.read`、`revision:candidate`），通过 `python run_agent.py --mode connected --list-tasks` / `--task <id>` 读取任务与需求；生成结果以 Candidate 提交：`python run_agent.py --mode connected --submit-candidate --artifact-type test_point_set@1.0 --payload-file <file.json>`，固定 `autoPublish=false`。connected 模式不会自动同步或发布 Skill。
- **share 模式（独立分享操作）**：作者确认 Skill 可用后，显式执行 `python run_agent.py --mode share --sync-skills test-point-generation`（Token 需 `skill:sync`），只创建 SYNCED_DRAFT；发布由具备项目 `agent.manage` 权限的 Web 用户在平台执行，范围仅限当前项目。

## 执行流程

1. local 模式从本地链式记录读取已确认的需求分析 Revision；connected 模式通过 TestWeave Gateway 读取目标记录及已确认的需求分析修订，不直接访问数据库。
2. 若需求分析未确认、仍有阻塞问题或记录状态不可继续，立即停止。
3. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
4. 按风险、边界和业务规则生成测试点，使用稳定引用连接上游对象。
5. 校验 JSON 后，local 模式用 `--record-submit` 存入本地记录等待人工确认；connected 模式通过 Gateway 提交候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 不接受未确认或只截取局部的需求分析作为上游。
- 不生成具体测试步骤或测试用例。
- `allowCaseGeneration` 只是候选建议，不能代替人工确认。
- 不确认、发布或直接写入正式测试点。
- 不自行修订上游需求分析。

本地使用不需要注册、同步和发布；只有平台 AI 测试设计工作台调用时，才要求把当前版本显式同步（share 模式）并由授权用户发布为不可变快照。
