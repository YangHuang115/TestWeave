<template>
  <div class="side-panel">
    <div class="panel-header">
      <h4>🚀 进行中的任务</h4>
    </div>

    <div class="state-container" v-if="loading">
      <span>加载中...</span>
    </div>

    <div class="state-container empty-state" v-else-if="items.length === 0">
      <span>暂无进行中的测试任务</span>
    </div>

    <div class="task-list" v-else>
      <div v-for="task in items" :key="task.id" class="task-card">
        <div class="task-header">
          <span class="task-no">TASK-{{ task.task_no }}</span>
          <span class="role-badge" :class="task.role.toLowerCase()">
            {{ task.role === 'OWNER' ? '负责人' : '参与人' }}
          </span>
        </div>

        <div class="task-title">{{ task.title }}</div>

        <div class="task-footer">
          <span class="version-name" v-if="task.version_name">
            {{ task.version_name }}
          </span>
          <router-link
            :to="`/projects/${projectId}/tasks/${task.id}`"
            class="detail-link"
          >
            查看任务 →
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkbenchInProgressTask } from '../api'

defineProps<{
  projectId: string
  items: WorkbenchInProgressTask[]
  loading: boolean
}>()
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

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-card {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 12px 14px;
}

.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.task-no {
  color: #818cf8;
  font-size: 12px;
  font-weight: 600;
}

.role-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.role-badge.owner {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}

.role-badge.participant {
  background: rgba(148, 163, 184, 0.15);
  color: #cbd5e1;
}

.task-title {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
}

.task-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.version-name {
  color: #64748b;
}

.detail-link {
  color: #818cf8;
  text-decoration: none;
}

.detail-link:hover {
  text-decoration: underline;
}
</style>
