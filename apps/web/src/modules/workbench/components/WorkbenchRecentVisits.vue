<template>
  <div class="bottom-panel">
    <div class="panel-header">
      <h4>📌 最近访问</h4>
    </div>

    <div class="state-container" v-if="loading">
      <span>加载最近访问...</span>
    </div>

    <div class="state-container empty-state" v-else-if="items.length === 0">
      <span>暂无最近访问记录</span>
    </div>

    <div class="visit-grid" v-else>
      <router-link
        v-for="item in items"
        :key="item.id"
        :to="item.target_route"
        class="visit-chip"
      >
        <span class="visit-type-icon">{{ getTypeIcon(item.resource_type) }}</span>
        <span class="visit-title">{{ item.title }}</span>
        <span class="visit-time">{{ formatDate(item.visited_at) }}</span>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkbenchRecentVisit } from '../api'

defineProps<{
  items: WorkbenchRecentVisit[]
  loading: boolean
}>()

function getTypeIcon(type: string) {
  const map: Record<string, string> = {
    requirement: '📋',
    test_task: '🚀',
    version: '🏷️',
    test_case: '🧪'
  }
  return map[type] || '📄'
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.bottom-panel {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 20px;

}

.panel-header h4 {
  color: #f8fafc;
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 14px 0;
}

.state-container {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.visit-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.visit-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 8px 14px;
  text-decoration: none;
  transition: all 0.15s;
}

.visit-chip:hover {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.3);
}

.visit-type-icon {
  font-size: 14px;
}

.visit-title {
  color: #cbd5e1;
  font-size: 13px;
  font-weight: 500;
}

.visit-time {
  color: #64748b;
  font-size: 11px;
}
</style>
