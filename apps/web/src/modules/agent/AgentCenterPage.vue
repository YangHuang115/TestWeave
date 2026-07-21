<template>
  <div class="agent-center-container">
    <!-- 头部横幅 -->
    <div class="runtime-banner">
      <span class="warning-icon">⚠️</span>
      <span>AI 运行期引擎 (AI Runtime Engine) 尚未启用接入，当前所有能力处于展示模型阶段。</span>
    </div>

    <!-- 主布局网格 -->
    <div class="agent-grid">
      <!-- 技能与工作流管理卡片 -->
      <div class="agent-card">
        <h3>⚡ 智能体技能与工作流 (Skills & Workflows)</h3>
        <p class="card-desc">定义智能体在测试生成、用例审核、缺陷定位时的核心策略。</p>
        <div class="item-list">
          <div class="list-item">
            <span class="item-title">技能: 需求分析 (requirements_analyzer)</span>
            <span class="item-badge">系统</span>
          </div>
          <div class="list-item">
            <span class="item-title">技能: 测试点生成 (testpoint_generator)</span>
            <span class="item-badge">系统</span>
          </div>
          <div class="list-item">
            <span class="item-title">工作流: 用例自动审核 (test_case_auto_audit)</span>
            <span class="item-badge workflow">工作流</span>
          </div>
        </div>
      </div>

      <!-- LLM Provider & 模型配置卡片 -->
      <div class="agent-card">
        <h3>🤖 模型提供商 (LLM Providers & Models)</h3>
        <p class="card-desc">配置平台所对接的大型语言模型凭证与默认分配规则。</p>
        <div class="model-selectors">
          <div class="model-row">
            <label>默认推理模型:</label>
            <select disabled>
              <option>Gemini 2.0 Pro (已禁用)</option>
              <option>Claude 3.5 Sonnet (已禁用)</option>
            </select>
          </div>
          <div class="model-row">
            <label>默认分析模型:</label>
            <select disabled>
              <option>Gemini 2.0 Flash (已禁用)</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Agent Runs 运行日志与评测卡片 -->
      <div class="agent-card wide">
        <h3>📊 智能体执行运行 (Agent Runs & Evaluations)</h3>
        <p class="card-desc">监控多智能体并发测试点分析、自动化回归以及生成评测质量结果。</p>
        <div class="empty-state">
          <div class="empty-icon">📂</div>
          <p>当前无 Agent 运行记录，等待 AI Runtime 服务启动。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Agent Center Container
</script>

<style scoped>
.agent-center-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
  width: 100%;
}

.runtime-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  color: #f59e0b;
  padding: 14px 20px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
}

.warning-icon {
  font-size: 18px;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.agent-card {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.agent-card.wide {
  grid-column: span 2;
}

h3 {
  color: #f1f5f9;
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}

.card-desc {
  color: #94a3b8;
  font-size: 13px;
  margin-bottom: 20px;
}

.item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(15, 23, 42, 0.4);
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.item-title {
  color: #cbd5e1;
  font-size: 13px;
  font-family: monospace;
}

.item-badge {
  font-size: 11px;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.3);
  padding: 2px 8px;
  border-radius: 4px;
}

.item-badge.workflow {
  background: rgba(139, 92, 246, 0.2);
  color: #c084fc;
  border: 1px solid rgba(139, 92, 246, 0.3);
}

.model-selectors {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.model-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-row label {
  color: #94a3b8;
  font-size: 12px;
}

.model-row select {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #64748b;
  padding: 10px;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  cursor: not-allowed;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  text-align: center;
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 12px;
  color: #475569;
}

.empty-state p {
  color: #64748b;
  font-size: 13px;
}
</style>
