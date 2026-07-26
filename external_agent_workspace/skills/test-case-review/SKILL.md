---
name: test-case-review
description: 评审 TestWeave 候选测试用例的可执行性、追踪性、覆盖和重复问题；当需要字段级问题与修订建议时使用。
---

# TestWeave 测试用例评审

评审已确认进入评审阶段的候选用例，输出可定位到字段的发现和修订请求。

## 执行流程

1. 通过 TestWeave Gateway 读取目标记录、候选用例及可用上游证据，不直接访问数据库。
2. 读取本目录的 `prompt.md`、`input.schema.json` 和 `output.schema.json`。
3. 上游链路完整时使用 `TRACEABLE`；只有用例本体时使用 `INTRINSIC`，不得伪造覆盖率。
4. 对每个问题给出准确 `caseRef`、`fieldPath`、证据引用、严重度和可执行建议。
5. 校验 JSON 后通过 Gateway 提交评审候选稿，并保持 `autoPublish=false`。
6. 遇到 `BLOCKED`、`NEEDS_SELECTION` 或 `NOT_FOUND` 时停止并把原因交给用户处理。

## 强制边界

- 只评审，不直接重写测试用例。
- 不把建议自动应用为修订，也不替用户接受或拒绝发现。
- 不确认、发布或绕过人工评审门禁。
- 缺少上游证据时不得输出虚假的规则或测试点覆盖结论。
- 不把密钥、令牌或敏感原文写入输出。

平台使用此 Skill 前必须先把当前版本显式同步并注册到目标项目；仅在本地 Agent 中调用时无需注册。
