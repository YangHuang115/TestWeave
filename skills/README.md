# TestWeave Skills

Skill 是单一职责、版本化、结构化、可授权、可追踪和可评测的专业测试能力包，不等于一段 Prompt。完整规则见 [AI Skill 开发规范](../docs/standards/ai-skill.md) 和 [AI 架构](../docs/architecture/ai-architecture.md)。

## 当前状态

当前没有已实现 Skill。`_template/` 仅用于创建新 Skill 的目录与契约模板，不能被注册为生产能力，也没有任何评估通过结论。

## 创建方式

1. 复制 `_template/` 为语义明确的 kebab-case 目录。
2. 在 `SKILL.md` 写清职责、不负责内容、版本、权限和失败语义。
3. 定义可解析的输入/输出 JSON Schema，禁止用自由文本承担协议。
4. 编写 Prompt/规则、Tool 白名单、模型要求、校验器和执行记录字段。
5. 建立正常、边界、注入和历史失败案例的固定评估集。
6. 记录基线和候选版本对比，通过审查后才能发布。
7. 在本文件“已实现 Skills”中登记真实状态和证据。

## 已实现 Skills

无。
