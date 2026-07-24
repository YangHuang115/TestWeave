<template>
  <div class="bottom-panel">
    <div class="panel-header">
      <h4>📋 我负责的剩余需求</h4>
      <span class="total-tag" v-if="total > 0">{{ total }} 个待分析/处理需求</span>
    </div>

    <div class="state-container" v-if="loading">
      <span>加载需求中...</span>
    </div>

    <div class="state-container empty-state" v-else-if="items.length === 0">
      <span>已完成所有所负责需求的测试设计</span>
    </div>

    <div class="req-table" v-else>
      <div v-for="req in items" :key="req.id" class="req-row">
        <div class="req-info">
          <span class="req-no">{{ req.requirement_no }}</span>
          <span class="req-title">{{ req.title }}</span>
        </div>

        <div class="req-meta">
          <span class="priority-tag" :class="req.priority.toLowerCase()">
            {{ req.priority }}
          </span>
          <span class="version-tag" v-if="req.version_name">
            🏷️ {{ req.version_name }}
          </span>
          <router-link :to="req.target_route" class="link-btn">
            需求详情 →
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkbenchRemainingRequirement } from '../api'

defineProps<{
  items: WorkbenchRemainingRequirement[]
  total: number
  loading: boolean
}>()
</script>

<style scoped>
.bottom-panel {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 20px;

}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-header h4 {
  color: #f8fafc;
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.total-tag {
  color: #64748b;
  font-size: 12px;
}

.state-container {
  padding: 30px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.req-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.req-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 10px 14px;
}

.req-row:hover {
  background: rgba(30, 41, 59, 0.6);
}

.req-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.req-no {
  color: #818cf8;
  font-weight: 600;
  font-size: 13px;
}

.req-title {
  color: #e2e8f0;
  font-size: 13px;
}

.req-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.priority-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}

.priority-tag.high {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.priority-tag.medium {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.priority-tag.low {
  background: rgba(100, 116, 139, 0.15);
  color: #94a3b8;
}

.version-tag {
  color: #64748b;
  font-size: 12px;
}

.link-btn {
  color: #818cf8;
  font-size: 12px;
  text-decoration: none;
}

.link-btn:hover {
  text-decoration: underline;
}
</style>
