<template>
  <div class="side-panel">
    <div class="panel-header">
      <h4>🤖 Agent 运行状态</h4>
    </div>

    <div class="state-container" v-if="loading">
      <span>加载 Agent 状态中...</span>
    </div>

    <div class="state-container empty-state" v-else-if="items.length === 0">
      <span>近 7 天暂无活跃的 AI Run</span>
    </div>

    <div class="run-list" v-else>
      <div v-for="run in items" :key="run.id" class="run-card">
        <div class="run-header">
          <span class="capability-title">
            {{ run.capability_name || 'AI 测试设计' }}
          </span>
          <span :class="['status-badge', run.status.toLowerCase()]">
            {{ formatStatus(run.status) }}
          </span>
        </div>

        <div class="run-context" v-if="run.task_title">
          关联任务: {{ run.task_title }}
        </div>

        <div class="error-summary" v-if="run.error_summary">
          ⚠️ {{ run.error_summary }}
        </div>

        <div class="run-footer">
          <span class="time-text">{{ formatDate(run.updated_at) }}</span>

          <router-link
            :to="`/projects/${projectId}/ai-test-design?runId=${run.id}`"
            class="action-link"
          >
            进入 Run →
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkbenchAgentRunItem } from '../api'

defineProps<{
  projectId: string
  items: WorkbenchAgentRunItem[]
  loading: boolean
}>()

function formatStatus(status: string) {
  const map: Record<string, string> = {
    PENDING: '等待调度',
    RUNNING: '运行中',
    WAITING_HUMAN: '待确认',
    WAITING_RETRY: '待重试',
    FAILED: '运行失败',
    SUCCEEDED: '已完成'
  }
  return map[status] || status
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.side-panel {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 16px 18px;

}

.panel-header h4 {
  color: #f8fafc;
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 14px 0;
}

.state-container {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.run-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-card {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 12px 14px;
}

.run-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.capability-title {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 500;
}

.status-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.status-badge.waiting_human {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.status-badge.running {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
}

.status-badge.failed {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
}

.run-context {
  color: #94a3b8;
  font-size: 11px;
  margin-bottom: 6px;
}

.error-summary {
  background: rgba(239, 68, 68, 0.1);
  color: #fca5a5;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 6px;

}

.run-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.time-text {
  color: #64748b;
}

.action-link {
  color: #38bdf8;
  text-decoration: none;
}

.action-link:hover {
  text-decoration: underline;
}
</style>
