---
name: test-case-generation
description: 根据已人工确认且允许继续的 TestWeave 测试点生成结构化候选测试用例；当需要形成可执行步骤、数据和预期时使用。
---

# TestWeave 测试用例生成

把已确认测试点转换为可执行、可追踪、可评审的测试用例候选稿。

## 执行流程

1. 通过 TestWeave Gateway 读取目标记录和已确认的测试点修订，不直接访问数据库。
2. 只处理 `allowCaseGeneration=true` 的已确认测试点；否则停止。
3. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
4. 为每条用例指定唯一主测试点引用，并写出前置条件、测试数据、步骤、核心预期、观察点和清理动作。
5. 校验 JSON 后通过 Gateway 提交候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 不使用未确认测试点，也不绕过 `allowCaseGeneration`。
- 不编造账号、环境、接口或业务规则。
- 不确认、发布或直接覆盖正式测试用例。
- 不在本阶段给出最终评审结论。
- 不自行修订上游需求分析或测试点。

平台使用此 Skill 前必须先把当前版本显式同步并注册到目标项目；仅在本地 Agent 中调用时无需注册。
