# Changelog

## 1.1.0

- SKILL.md 增加「运行模式」章节：local（默认、无 Token、不调用 Gateway）、connected（显式连接、只读任务/需求并提交 Candidate）、share（独立分享，仅创建 SYNCED_DRAFT）。
- 明确本地使用不需要注册、同步和发布；Prompt、输入输出 Schema 与模型策略均未变化，不影响历史评测基线。

## 1.0.0

- 将原代码内嵌的需求分析指令迁移为可见、可编辑、可注册的 Skill 包。
- 增加输入输出 Schema、来源证据约束、Human Gate 边界和提示注入防护。
- 增加合成样例与基础评测用例；尚未执行真实模型评测。
