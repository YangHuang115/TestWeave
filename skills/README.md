# TestWeave Skills

Skill 是单一职责、版本化、结构化、可授权、可追踪和可评测的专业测试能力包，不等于一段 Prompt。完整规则见 [AI Skill 开发规范](../docs/standards/ai-skill.md) 和 [AI 架构](../docs/architecture/ai-architecture.md)。

## 当前状态

本目录只保存开发模板，不保存用户正在编辑的 Skill 源。四个已实现 Skill 位于用户的 `external_agent_workspace/skills/`，通过 Gateway 显式同步为项目级不可变版本。`_template/` 本身不能被注册为生产能力，也没有任何评估通过结论。

## 创建方式

1. 把 `_template/` 复制到 `external_agent_workspace/skills/<kebab-case-name>/`。
2. 在 `SKILL.md` 写清职责、不负责内容、版本、权限和失败语义。
3. 定义可解析的输入/输出 JSON Schema，禁止用自由文本承担协议。
4. 编写 Prompt/规则、Tool 白名单、模型要求、校验器和执行记录字段。
5. 建立正常、边界、注入和历史失败案例的固定评估集。
6. 记录基线和候选版本对比，通过审查后才能发布。
7. 通过 `POST /external/v1/skills/sync-draft` 同步，人工审核后再发布。

## 已实现 Skills

- `requirement-analysis`
- `test-point-generation`
- `test-case-generation`
- `test-case-review`

以上只登记稳定 ID；Prompt、Schema、样例和 CHANGELOG 均以外部工作区源文件及服务器版本快照为准。
