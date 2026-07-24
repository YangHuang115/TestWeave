<template>
  <div class="summary-cards-grid">
    <div
      class="summary-card text-card clickable"
      @click="$emit('select-section', 'requirements')"
    >
      <div class="card-header">
        <span class="card-title">剩余需求</span>
        <span class="card-icon">📋</span>
      </div>
      <div class="card-value red-accent">
        {{ summary?.remaining_requirements_count ?? 0 }}
      </div>
      <div class="card-footer">
        <span>我负责且未完成测试设计的需求</span>
      </div>
    </div>

    <div
      class="summary-card text-card clickable active-border"
      @click="$emit('select-section', 'todos')"
    >
      <div class="card-header">
        <span class="card-title">我的待办</span>
        <span class="card-icon">⚡</span>
      </div>
      <div class="card-value primary-accent">
        {{ summary?.my_todos_count ?? 0 }}
      </div>
      <div class="card-footer">
        <span>首屏可处理核心待办</span>
      </div>
    </div>

    <div
      class="summary-card text-card clickable"
      @click="$emit('select-section', 'tasks')"
    >
      <div class="card-header">
        <span class="card-title">进行中任务</span>
        <span class="card-icon">🚀</span>
      </div>
      <div class="card-value blue-accent">
        {{ summary?.in_progress_tasks_count ?? 0 }}
      </div>
      <div class="card-footer">
        <span>我负责或参与的活跃测试任务</span>
      </div>
    </div>

    <div
      class="summary-card text-card clickable"
      @click="$emit('select-section', 'agent-runs')"
    >
      <div class="card-header">
        <span class="card-title">等待人工确认</span>
        <span class="card-icon">🤖</span>
      </div>
      <div class="card-value warning-accent">
        {{ summary?.waiting_human_count ?? 0 }}
      </div>
      <div class="card-footer">
        <span>AI Agent 运行等待确认节点</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkbenchSummary } from '../api'

defineProps<{
  summary: WorkbenchSummary | null
}>()

defineEmits<{
  (e: 'select-section', section: string): void
}>()
</script>

<style scoped>
.summary-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1024px) {
  .summary-cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .summary-cards-grid {
    grid-template-columns: 1fr;
  }
}

.summary-card {
  background: rgba(30, 41, 59, 0.45);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 20px;
  transition: all 0.2s ease-in-out;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.summary-card.clickable {
  cursor: pointer;
}

.summary-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
}

.summary-card.active-border {
  border-color: rgba(99, 102, 241, 0.3);
  background: rgba(99, 102, 241, 0.06);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  color: #94a3b8;
  font-size: 13px;
  font-weight: 500;
}

.card-icon {
  font-size: 16px;
}

.card-value {
  font-size: 32px;
  font-weight: 700;
  margin: 12px 0 6px 0;
  line-height: 1;
}

.red-accent {
  color: #f87171;
}

.primary-accent {
  color: #818cf8;
}

.blue-accent {
  color: #38bdf8;
}

.warning-accent {
  color: #fbbf24;
}

.card-footer {
  font-size: 12px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
