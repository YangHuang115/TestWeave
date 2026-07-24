---
name: replace-with-skill-name
description: TODO：一句话说明单一职责和触发场景
version: 0.1.0
status: template
---

# Skill 名称

> 本文件是模板。复制后必须替换全部 TODO；未经实现、评估和发布，不得标记为可用 Skill。

## 职责

- TODO：本 Skill 负责什么。

## 不负责

- TODO：明确相邻阶段和禁止副作用。

## 所属 Workflow 阶段

- Workflow：TODO
- 节点：TODO
- 前置人工门：TODO

## 版本

- Skill 版本：`0.1.0`
- Prompt 版本：TODO
- 输入 Schema：`input.schema.json`
- 输出 Schema：`output.schema.json`

## 输入与上下文

- 必填输入：TODO
- ProjectContext / RequirementVersion / 决策快照：TODO
- 大小与分片策略：TODO

## 输出与校验

- 结构化输出：TODO
- 业务校验器：TODO
- 证据和不确定性：TODO
- `needs_human` 的原因码、提示和必需输入：TODO
- 校验失败语义：TODO

## 模型与工具

- 模型能力要求：TODO
- 允许 Tool 白名单：TODO
- 禁止 Tool：TODO
- 权限和副作用等级：TODO

## 错误、重试与追踪

- 可重试错误：TODO
- 不可重试错误：TODO
- 超时/预算：TODO
- 运行记录和关联 ID：TODO

## 敏感信息

- 输入过滤与脱敏：TODO
- 输出/日志禁止内容：TODO

## 评估

- 固定数据集版本：TODO
- 指标与发布阈值：TODO
- 基线版本：TODO
- 评估结果位置：`evaluations/`

## 历史失败案例

当前无。真实发生后记录案例 ID、版本、根因、修复和回归覆盖；不得伪造案例。
