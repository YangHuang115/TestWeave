<template>
  <div class="todo-panel">
    <div class="panel-header">
      <div class="panel-title">
        <h3>⚡ 我的待办</h3>
        <span class="count-badge" v-if="total > 0">{{ total }}</span>
      </div>

      <!-- 筛选组 -->
      <div class="filter-group">
        <select
          v-model="selectedPriority"
          class="select-control"
          @change="onFilterChange"
        >
          <option value="">全优先级</option>
          <option value="HIGH">高优先级</option>
          <option value="MEDIUM">中优先级</option>
          <option value="LOW">低优先级</option>
        </select>

        <label class="checkbox-label">
          <input
            type="checkbox"
            v-model="isOverdueOnly"
            @change="onFilterChange"
          />
          <span>只看逾期</span>
        </label>
      </div>
    </div>

    <!-- 加载中 -->
    <div class="state-container" v-if="loading">
      <div class="spinner"></div>
      <span>加载待办中...</span>
    </div>

    <!-- 错误重试 -->
    <div class="state-container error-state" v-else-if="error">
      <span>{{ error }}</span>
      <button class="retry-btn" @click="$emit('retry')">重试</button>
    </div>

    <!-- 空状态 -->
    <div class="state-container empty-state" v-else-if="items.length === 0">
      <div class="empty-icon">🎉</div>
      <span>暂无待办事项，当前所有工作均已就绪</span>
    </div>

    <!-- 待办列表 -->
    <div class="todo-list" v-else>
      <div
        v-for="item in items"
        :key="item.id"
        class="todo-item"
        :class="{ blocked: item.urgency === 'BLOCKED', overdue: item.urgency === 'OVERDUE' }"
      >
        <div class="todo-main">
          <div class="todo-title-row">
            <span
              class="urgency-tag"
              v-if="item.urgency === 'BLOCKED'"
            >
              阻塞确认
            </span>
            <span
              class="urgency-tag overdue"
              v-else-if="item.urgency === 'OVERDUE'"
            >
              已逾期
            </span>

            <span class="todo-title">{{ item.title }}</span>

            <span class="sub-badge" v-if="item.sub_item_count > 1">
              {{ item.sub_item_count }} 项
            </span>
          </div>

          <div class="todo-meta-row">
            <span
              :class="['priority-badge', item.priority.toLowerCase()]"
            >
              {{ item.priority }}
            </span>
            <span class="meta-tag" v-if="item.version_name">
              🏷️ {{ item.version_name }}
            </span>
            <span class="meta-tag" v-if="item.due_at">
              ⏰ {{ formatDate(item.due_at) }}
            </span>
          </div>
        </div>

        <div class="todo-actions">
          <router-link
            :to="item.target_route"
            class="action-btn primary-btn"
            tabindex="0"
          >
            去处理
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { WorkbenchTodoItem } from '../api'

defineProps<{
  items: WorkbenchTodoItem[]
  total: number
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  (e: 'filter', filters: { priority?: string; is_overdue?: boolean }): void
  (e: 'retry'): void
}>()

const selectedPriority = ref('')
const isOverdueOnly = ref(false)

function onFilterChange() {
  emit('filter', {
    priority: selectedPriority.value || undefined,
    is_overdue: isOverdueOnly.value
  })
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
.todo-panel {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 20px;

}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;

}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-title h3 {
  color: #f8fafc;
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.count-badge {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.3);
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.select-control {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
}

.state-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #94a3b8;
  font-size: 14px;
  gap: 12px;
}

.empty-icon {
  font-size: 36px;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.retry-btn {
  background: #4f46e5;
  color: white;
  border: none;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.todo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-left: 3px solid #6366f1;
  border-radius: 8px;
  padding: 14px 16px;
  transition: background 0.15s;
}

.todo-item:hover {
  background: rgba(30, 41, 59, 0.7);
}

.todo-item.blocked {
  border-left-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.todo-item.overdue {
  border-left-color: #f59e0b;
}

.todo-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.todo-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.urgency-tag {
  background: #ef4444;
  color: white;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}

.urgency-tag.overdue {
  background: #f59e0b;
}

.todo-title {
  color: #e2e8f0;
  font-size: 14px;
  font-weight: 500;
}

.sub-badge {
  background: rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
}

.todo-meta-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.priority-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}

.priority-badge.high {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.priority-badge.medium {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.priority-badge.low {
  background: rgba(100, 116, 139, 0.15);
  color: #94a3b8;
}

.meta-tag {
  color: #64748b;
  font-size: 12px;
}

.action-btn.primary-btn {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: white;
  text-decoration: none;
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 6px;
  font-weight: 500;
  transition: opacity 0.2s;
  display: inline-block;
}

.action-btn.primary-btn:hover {
  opacity: 0.9;
}
</style>
