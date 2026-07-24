<template>
  <div class="workbench-container">
    <!-- 顶部 Header 与快捷入口 -->
    <div class="workbench-header">
      <div class="header-left">
        <h2>工作台</h2>
        <span class="sub-text">当前项目个人待办、活跃任务与 Agent 运行概览</span>
      </div>

      <div class="header-actions">
        <button
          class="action-btn secondary"
          :disabled="!hasVersionPermission"
          @click="onUploadRequirement"
          title="上传并分析需求"
        >
          📤 上传需求
        </button>

        <button
          class="action-btn primary"
          :disabled="!hasTaskPermission"
          @click="onCreateTask"
          title="新建测试用例设计任务"
        >
          ➕ 新建用例设计任务
        </button>
      </div>
    </div>

    <!-- 四张概要指标卡片 -->
    <WorkbenchSummaryCards
      :summary="summary"
      @select-section="onSelectSection"
    />

    <!-- 中间主内容区：待办 (左) + 任务 & Agent (右) -->
    <div class="workbench-grid main-grid">
      <div class="grid-left" ref="todoRef">
        <WorkbenchTodoList
          :items="todos"
          :total="todosTotal"
          :loading="todosLoading"
          :error="todosError"
          @filter="onTodoFilter"
          @retry="fetchTodos"
        />
      </div>

      <div class="grid-right">
        <WorkbenchInProgressTasks
          :project-id="projectId"
          :items="inProgressTasks"
          :loading="tasksLoading"
        />

        <WorkbenchAgentRuns
          :project-id="projectId"
          :items="agentRuns"
          :loading="runsLoading"
        />
      </div>
    </div>

    <!-- 底部区域：剩余需求 (左) + 最近访问 (右) -->
    <div class="workbench-grid bottom-grid">
      <div class="grid-left">
        <WorkbenchRemainingRequirements
          :items="remainingReqs"
          :total="remainingReqsTotal"
          :loading="reqsLoading"
        />
      </div>

      <div class="grid-right">
        <WorkbenchRecentVisits
          :items="recentVisits"
          :loading="visitsLoading"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/shared/stores/project'
import {
  workbenchApi,
  type WorkbenchAgentRunItem,
  type WorkbenchInProgressTask,
  type WorkbenchRecentVisit,
  type WorkbenchRemainingRequirement,
  type WorkbenchSummary,
  type WorkbenchTodoItem
} from './api'

import WorkbenchSummaryCards from './components/WorkbenchSummaryCards.vue'
import WorkbenchTodoList from './components/WorkbenchTodoList.vue'
import WorkbenchInProgressTasks from './components/WorkbenchInProgressTasks.vue'
import WorkbenchAgentRuns from './components/WorkbenchAgentRuns.vue'
import WorkbenchRemainingRequirements from './components/WorkbenchRemainingRequirements.vue'
import WorkbenchRecentVisits from './components/WorkbenchRecentVisits.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

const projectId = computed(() => (route.params.projectId as string) || '')

// 权限感知的快捷按钮
const hasVersionPermission = computed(() => projectStore.hasPermission('version.manage'))
const hasTaskPermission = computed(() => projectStore.hasPermission('task.manage'))

// 数据状态
const summary = ref<WorkbenchSummary | null>(null)
const todos = ref<WorkbenchTodoItem[]>([])
const todosTotal = ref(0)
const todosLoading = ref(false)
const todosError = ref<string | null>(null)

const inProgressTasks = ref<WorkbenchInProgressTask[]>([])
const tasksLoading = ref(false)

const agentRuns = ref<WorkbenchAgentRunItem[]>([])
const runsLoading = ref(false)

const remainingReqs = ref<WorkbenchRemainingRequirement[]>([])
const remainingReqsTotal = ref(0)
const reqsLoading = ref(false)

const recentVisits = ref<WorkbenchRecentVisit[]>([])
const visitsLoading = ref(false)

// 当前筛选条件
const todoFilterParams = ref<{ priority?: string; is_overdue?: boolean }>({})

// AbortController 控制快速切换项目请求失效
let currentAbortController: AbortController | null = null

function fetchAllData() {
  if (!projectId.value) return

  // 取消上一个项目的未完成请求
  if (currentAbortController) {
    currentAbortController.abort()
  }
  currentAbortController = new AbortController()
  const signal = currentAbortController.signal

  fetchSummary(signal)
  fetchTodos(signal)
  fetchInProgressTasks(signal)
  fetchAgentRuns(signal)
  fetchRemainingRequirements(signal)
  fetchRecentVisits(signal)
}

async function fetchSummary(signal?: AbortSignal) {
  try {
    const res = await workbenchApi.getSummary(projectId.value, signal)
    summary.value = res
  } catch (err: any) {
    if (isAbortError(err)) return
  }
}

async function fetchTodos(signal?: AbortSignal) {
  todosLoading.value = true
  todosError.value = null
  try {
    const res = await workbenchApi.getTodos(
      projectId.value,
      {
        priority: todoFilterParams.value.priority,
        is_overdue: todoFilterParams.value.is_overdue,
        limit: 50
      },
      signal
    )
    todos.value = res.items
    todosTotal.value = res.total
  } catch (err: any) {
    if (isAbortError(err)) return
    todosError.value = '加载待办失败，请重试'
  } finally {
    todosLoading.value = false
  }
}

async function fetchInProgressTasks(signal?: AbortSignal) {
  tasksLoading.value = true
  try {
    const res = await workbenchApi.getInProgressTasks(projectId.value, { limit: 10 }, signal)
    inProgressTasks.value = res.items
  } catch (err: any) {
    if (isAbortError(err)) return
  } finally {
    tasksLoading.value = false
  }
}

async function fetchAgentRuns(signal?: AbortSignal) {
  runsLoading.value = true
  try {
    const res = await workbenchApi.getAgentRuns(projectId.value, { limit: 10 }, signal)
    agentRuns.value = res.items
  } catch (err: any) {
    if (isAbortError(err)) return
  } finally {
    runsLoading.value = false
  }
}

async function fetchRemainingRequirements(signal?: AbortSignal) {
  reqsLoading.value = true
  try {
    const res = await workbenchApi.getRemainingRequirements(projectId.value, { limit: 10 }, signal)
    remainingReqs.value = res.items
    remainingReqsTotal.value = res.total
  } catch (err: any) {
    if (isAbortError(err)) return
  } finally {
    reqsLoading.value = false
  }
}

async function fetchRecentVisits(signal?: AbortSignal) {
  visitsLoading.value = true
  try {
    const res = await workbenchApi.getRecentVisits(projectId.value, { limit: 10 }, signal)
    recentVisits.value = res.items
  } catch (err: any) {
    if (isAbortError(err)) return
  } finally {
    visitsLoading.value = false
  }
}

function isAbortError(err: any) {
  return err?.name === 'AbortError' || err?.code === 'ERR_CANCELED'
}

function onTodoFilter(filters: { priority?: string; is_overdue?: boolean }) {
  todoFilterParams.value = filters
  if (currentAbortController) {
    fetchTodos(currentAbortController.signal)
  } else {
    fetchTodos()
  }
}

function onSelectSection(section: string) {
  if (section === 'todos') {
    // 聚焦待办
  } else if (section === 'requirements') {
    router.push(`/projects/${projectId.value}/versions`)
  } else if (section === 'tasks') {
    router.push(`/projects/${projectId.value}/tasks`)
  } else if (section === 'agent-runs') {
    router.push(`/projects/${projectId.value}/ai-test-design`)
  }
}

function onUploadRequirement() {
  if (hasVersionPermission.value) {
    router.push(`/projects/${projectId.value}/versions`)
  }
}

function onCreateTask() {
  if (hasTaskPermission.value) {
    router.push(`/projects/${projectId.value}/tasks`)
  }
}

// 监听项目 ID 变化重新加载
watch(
  projectId,
  (newId) => {
    if (newId) {
      fetchAllData()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  if (currentAbortController) {
    currentAbortController.abort()
  }
})
</script>

<style scoped>
.workbench-container {
  padding: 24px;
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  box-sizing: border-box;
}

.workbench-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.header-left h2 {
  color: #f8fafc;
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 6px 0;
}

.sub-text {
  color: #94a3b8;
  font-size: 13px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.action-btn {
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.secondary {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
}

.action-btn.secondary:hover:not(:disabled) {
  background: rgba(51, 65, 85, 0.8);
  color: #f8fafc;
}

.action-btn.primary {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.action-btn.primary:hover:not(:disabled) {
  opacity: 0.95;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}

.workbench-grid {
  display: grid;
  grid-template-columns: 7fr 5fr;
  gap: 20px;
  margin-bottom: 20px;
}

@media (max-width: 1024px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}

.grid-right {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
</style>
