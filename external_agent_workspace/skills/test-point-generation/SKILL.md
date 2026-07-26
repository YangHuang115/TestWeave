---
name: test-point-generation
description: 根据已人工确认的 TestWeave 需求分析生成可追踪、可评审的结构化测试点；当需求分析已经通过 Human Gate 时使用。
---

# TestWeave 测试点生成

把已确认的完整需求分析转换为测试点候选稿，并保留规则、问题和模块关系的追踪链路。

## 执行流程

1. 通过 TestWeave Gateway 读取目标记录及已确认的需求分析修订，不直接访问数据库。
2. 若需求分析未确认、仍有阻塞问题或记录状态不可继续，立即停止。
3. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
4. 按风险、边界和业务规则生成测试点，使用稳定引用连接上游对象。
5. 校验 JSON 后通过 Gateway 提交候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 不接受未确认或只截取局部的需求分析作为上游。
- 不生成具体测试步骤或测试用例。
- `allowCaseGeneration` 只是候选建议，不能代替人工确认。
- 不确认、发布或直接写入正式测试点。
- 不自行修订上游需求分析。

平台使用此 Skill 前必须先把当前版本显式同步并注册到目标项目；仅在本地 Agent 中调用时无需注册。
