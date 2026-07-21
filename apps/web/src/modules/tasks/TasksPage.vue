<template>
  <div class="tasks-page">
    <!-- 头部及操作区 -->
    <div class="page-header">
      <div class="title-section">
        <h1>测试任务管理</h1>
        <p class="subtitle">跟踪并流转用例设计与测试执行任务生命周期</p>
      </div>
      <button class="btn btn-primary btn-glow" @click="openCreateDrawer">
        <span class="btn-icon">＋</span> 新建测试任务
      </button>
    </div>

    <!-- 工作台汇总面板 -->
    <div class="summary-grid" v-if="!summaryLoading">
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'my_draft_ready' }"
        @click="toggleQuickFilter('my_draft_ready')"
      >
        <div class="card-icon blue">📅</div>
        <div class="card-content">
          <span class="count">{{ summaryData.myDraftAndReadyCount }}</span>
          <span class="label">待我开始</span>
        </div>
      </div>
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'my_in_progress' }"
        @click="toggleQuickFilter('my_in_progress')"
      >
        <div class="card-icon indigo">⚡</div>
        <div class="card-content">
          <span class="count">{{ summaryData.myInProgressCount }}</span>
          <span class="label">我进行中的</span>
        </div>
      </div>
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'my_participant' }"
        @click="toggleQuickFilter('my_participant')"
      >
        <div class="card-icon violet">👥</div>
        <div class="card-content">
          <span class="count">{{ summaryData.myParticipantCount }}</span>
          <span class="label">我参与的</span>
        </div>
      </div>
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'blocked' }"
        @click="toggleQuickFilter('blocked')"
      >
        <div class="card-icon red">🛑</div>
        <div class="card-content">
          <span class="count-danger">{{ summaryData.blockedCount }}</span>
          <span class="label">项目阻塞中</span>
        </div>
      </div>
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'overdue' }"
        @click="toggleQuickFilter('overdue')"
      >
        <div class="card-icon orange">⏰</div>
        <div class="card-content">
          <span class="count-danger">{{ summaryData.overdueCount }}</span>
          <span class="label">已逾期</span>
        </div>
      </div>
      <div 
        class="summary-card" 
        :class="{ active: activeQuickFilter === 'due_soon' }"
        @click="toggleQuickFilter('due_soon')"
      >
        <div class="card-icon yellow">⏳</div>
        <div class="card-content">
          <span class="count-warning">{{ summaryData.dueSoonCount }}</span>
          <span class="label">即将到期 (3天内)</span>
        </div>
      </div>
    </div>
    <div class="summary-grid-skeleton" v-else>
      <div class="skeleton-card" v-for="i in 6" :key="i"></div>
    </div>

    <!-- 筛选过滤栏 -->
    <div class="filter-bar">
      <div class="search-input-wrapper">
        <span class="search-icon">🔍</span>
        <input 
          type="text" 
          v-model="filters.q" 
          placeholder="搜索任务编号或标题..." 
          @input="handleSearch"
          class="form-control"
        />
      </div>

      <div class="filter-controls">
        <!-- 版本筛选 -->
        <select v-model="filters.versionId" class="form-select" @change="fetchTasks">
          <option value="">所有版本</option>
          <option v-for="v in versions" :key="v.id" :value="v.id">
            {{ v.key }} ({{ v.name }})
          </option>
        </select>

        <!-- 类型筛选 -->
        <select v-model="filters.taskType" class="form-select" @change="fetchTasks">
          <option value="">所有类型</option>
          <option value="CASE_DESIGN">用例设计任务</option>
          <option value="TEST_EXECUTION" disabled>用例执行任务 (M06接入)</option>
        </select>

        <!-- 状态筛选 -->
        <select v-model="filters.status" class="form-select" @change="fetchTasks">
          <option value="">所有状态</option>
          <option value="DRAFT">草稿 (DRAFT)</option>
          <option value="READY">待开始 (READY)</option>
          <option value="IN_PROGRESS">进行中 (IN_PROGRESS)</option>
          <option value="BLOCKED">已阻塞 (BLOCKED)</option>
          <option value="COMPLETED">已完成 (COMPLETED)</option>
          <option value="CANCELLED">已取消 (CANCELLED)</option>
          <option value="ARCHIVED">已归档 (ARCHIVED)</option>
        </select>

        <!-- 负责人筛选 -->
        <select v-model="filters.ownerId" class="form-select" @change="fetchTasks">
          <option value="">所有负责人</option>
          <option v-for="m in members" :key="m.user_id" :value="m.user_id">
            {{ m.display_name }}
          </option>
        </select>

        <!-- 排序方式 -->
        <select v-model="filters.sortBy" class="form-select" @change="fetchTasks">
          <option value="updated_at">按最后更新排序</option>
          <option value="planned_end_at">按截止时间排序</option>
          <option value="priority">按优先级排序</option>
        </select>

        <!-- 排序顺序 -->
        <button class="btn-sort" @click="toggleSortOrder">
          {{ filters.sortOrder === 'asc' ? '▲ 正序' : '▼ 倒序' }}
        </button>

        <!-- 清理所有快捷/搜索过滤 -->
        <button class="btn btn-secondary btn-reset" @click="resetFilters">重置</button>
      </div>
    </div>

    <!-- 列表展示区 -->
    <div class="list-container">
      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>正在加载测试任务列表...</p>
      </div>

      <div v-else-if="errorMsg" class="error-state">
        <div class="error-icon">⚠️</div>
        <h3>数据加载错误</h3>
        <p>{{ errorMsg }}</p>
        <button class="btn btn-primary" @click="fetchTasks">重试</button>
      </div>

      <div v-else-if="tasks.length === 0" class="empty-state">
        <div class="empty-icon">📁</div>
        <h3>暂无测试任务</h3>
        <p>没有找到匹配当前筛选条件的测试任务，您可以尝试清除筛选或创建一个新任务。</p>
        <button class="btn btn-secondary" @click="resetFilters">清除筛选</button>
      </div>

      <div v-else class="table-responsive">
        <table class="tasks-table">
          <thead>
            <tr>
              <th width="120">编号</th>
              <th>任务标题</th>
              <th width="100">类型</th>
              <th width="120">状态</th>
              <th width="100">优先级</th>
              <th width="130">负责人</th>
              <th width="150">计划起止</th>
              <th width="100">关联需求</th>
              <th width="100">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tasks" :key="t.id" :class="{ 'overdue-row': t.isOverdue }">
              <td class="task-no-cell">
                <router-link :to="`/projects/${projectId}/test-tasks/${t.id}`" class="task-no-link">
                  {{ t.taskNo }}
                </router-link>
              </td>
              <td>
                <div class="task-title-wrapper">
                  <router-link :to="`/projects/${projectId}/test-tasks/${t.id}`" class="task-title-link">
                    {{ t.title }}
                  </router-link>
                  <div class="tags-wrapper" v-if="t.tagsJson && t.tagsJson.length > 0">
                    <span v-for="tag in t.tagsJson" :key="tag" class="task-tag">{{ tag }}</span>
                  </div>
                  <div class="blockage-desc" v-if="t.isBlocked && t.activeBlockageReason">
                    🛑 阻塞原因: {{ t.activeBlockageReason }}
                  </div>
                </div>
              </td>
              <td>
                <span class="type-badge" :class="t.taskType">
                  {{ t.taskType === 'CASE_DESIGN' ? '设计' : '执行' }}
                </span>
              </td>
              <td>
                <span class="status-badge" :class="t.status.toLowerCase()">
                  {{ formatStatus(t.status) }}
                </span>
              </td>
              <td>
                <span class="priority-badge" :class="t.priority.toLowerCase()">
                  {{ formatPriority(t.priority) }}
                </span>
              </td>
              <td class="text-secondary">{{ t.ownerName || '未指定' }}</td>
              <td>
                <div class="date-range">
                  <span class="start-date">{{ formatDateShort(t.plannedStartAt) }}</span>
                  <span class="split">~</span>
                  <span class="end-date" :class="{ danger: t.isOverdue }">
                    {{ formatDateShort(t.plannedEndAt) }}
                    <span class="overdue-tag" v-if="t.isOverdue">已超期</span>
                  </span>
                </div>
              </td>
              <td>
                <span class="requirement-count-badge">
                  {{ t.status === 'DRAFT' ? '配置中' : '已关联' }}
                </span>
              </td>
              <td>
                <div class="action-buttons">
                  <router-link :to="`/projects/${projectId}/test-tasks/${t.id}`" class="btn-action">
                    详情
                  </router-link>
                  <button 
                    v-if="t.status === 'COMPLETED' || t.status === 'CANCELLED'" 
                    class="btn-action archive-btn" 
                    @click="archiveTask(t)"
                  >
                    归档
                  </button>
                  <button 
                    v-if="t.status === 'ARCHIVED'" 
                    class="btn-action restore-btn" 
                    @click="restoreTask(t)"
                  >
                    激活
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页控制 -->
      <div class="pagination-bar" v-if="totalTasks > 0">
        <span class="total-info">共 {{ totalTasks }} 个任务</span>
        <div class="pagination-buttons">
          <button 
            class="btn btn-secondary" 
            :disabled="currentPage === 1" 
            @click="changePage(currentPage - 1)"
          >
            上一页
          </button>
          <span class="page-num">{{ currentPage }} / {{ totalPages }}</span>
          <button 
            class="btn btn-secondary" 
            :disabled="currentPage === totalPages" 
            @click="changePage(currentPage + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>

    <!-- 创建抽屉组件 -->
    <CreateTaskDrawer 
      v-if="createDrawerVisible" 
      :projectId="projectId" 
      :versions="versions"
      :members="members"
      @close="closeCreateDrawer" 
      @created="onTaskCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch, reactive } from "vue";
import { useRoute, useRouter } from "vue-router";
import { testTasksApi, TestTask } from "./api";
import { versionsApi, Version } from "../versions/api";
import { apiClient } from "../../shared/api/client";
import CreateTaskDrawer from "./CreateTaskDrawer.vue";

interface Member {
  user_id: string;
  display_name: string;
  role_id: string;
}

const route = useRoute();
const router = useRouter();
const projectId = computed(() => route.params.projectId as string);

// 状态定义
const tasks = ref<TestTask[]>([]);
const totalTasks = ref(0);
const loading = ref(false);
const errorMsg = ref("");

const versions = ref<Version[]>([]);
const members = ref<Member[]>([]);

// 汇总数据
const summaryLoading = ref(false);
const summaryData = ref({
  myDraftAndReadyCount: 0,
  myInProgressCount: 0,
  myParticipantCount: 0,
  blockedCount: 0,
  overdueCount: 0,
  dueSoonCount: 0,
  recentTasks: [] as TestTask[]
});

// 分页与排序
const limit = ref(15);
const currentPage = ref(1);
const totalPages = computed(() => Math.ceil(totalTasks.value / limit.value) || 1);

// 快捷过滤标记
const activeQuickFilter = ref<string>("");

// 统一筛选表单
const filters = reactive({
  q: "",
  versionId: "",
  taskType: "",
  status: "",
  ownerId: "",
  sortBy: "updated_at",
  sortOrder: "desc"
});

// 搜索防抖
let searchTimeout: ReturnType<typeof setTimeout> | null = null;
const handleSearch = () => {
  if (searchTimeout) clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    currentPage.value = 1;
    fetchTasks();
  }, 300);
};

// URL Query 参数双向绑定同步
const syncFiltersFromQuery = () => {
  const query = route.query;
  filters.q = (query.q as string) || "";
  filters.versionId = (query.versionId as string) || "";
  filters.taskType = (query.taskType as string) || "";
  filters.status = (query.status as string) || "";
  filters.ownerId = (query.ownerId as string) || "";
  filters.sortBy = (query.sortBy as string) || "updated_at";
  filters.sortOrder = (query.sortOrder as string) || "desc";
  currentPage.value = Number(query.page) || 1;
  activeQuickFilter.value = (query.quickFilter as string) || "";
};

const updateRouterQuery = () => {
  const query: Record<string, string | number> = {};
  if (filters.q) query.q = filters.q;
  if (filters.versionId) query.versionId = filters.versionId;
  if (filters.taskType) query.taskType = filters.taskType;
  if (filters.status) query.status = filters.status;
  if (filters.ownerId) query.ownerId = filters.ownerId;
  if (filters.sortBy) query.sortBy = filters.sortBy;
  if (filters.sortOrder) query.sortOrder = filters.sortOrder;
  if (currentPage.value > 1) query.page = currentPage.value;
  if (activeQuickFilter.value) query.quickFilter = activeQuickFilter.value;

  router.replace({ query });
};

// 快捷汇总过滤处理
const toggleQuickFilter = (type: string) => {
  if (activeQuickFilter.value === type) {
    activeQuickFilter.value = "";
  } else {
    activeQuickFilter.value = type;
  }
  currentPage.value = 1;
  fetchTasks();
};

// 抓取列表主数据
const fetchTasks = async () => {
  loading.value = true;
  errorMsg.value = "";
  updateRouterQuery();

  try {
    const offset = (currentPage.value - 1) * limit.value;
    
    // 构建 API query 选项
    const apiParams: Record<string, any> = {
      q: filters.q,
      versionId: filters.versionId || undefined,
      taskType: filters.taskType || undefined,
      status: filters.status || undefined,
      ownerId: filters.ownerId || undefined,
      sortBy: filters.sortBy,
      sortOrder: filters.sortOrder,
      limit: limit.value,
      offset: offset
    };

    // 快捷选项过滤条件叠加
    if (activeQuickFilter.value === "my_draft_ready") {
      apiParams.ownerId = await getMyUserId();
    } else if (activeQuickFilter.value === "my_in_progress") {
      apiParams.ownerId = await getMyUserId();
      apiParams.status = "IN_PROGRESS";
    } else if (activeQuickFilter.value === "my_participant") {
      apiParams.participantId = await getMyUserId();
    } else if (activeQuickFilter.value === "blocked") {
      apiParams.isBlocked = true;
    } else if (activeQuickFilter.value === "overdue") {
      apiParams.isOverdue = true;
    }

    const res = await testTasksApi.list(projectId.value, apiParams);
    
    // 如果是 my_draft_ready，前端再二次过滤状态为 DRAFT 或者是 READY 的数据以保精准
    if (activeQuickFilter.value === "my_draft_ready") {
      tasks.value = res.items.filter(t => t.status === "DRAFT" || t.status === "READY");
      totalTasks.value = tasks.value.length;
    } else if (activeQuickFilter.value === "due_soon") {
      // 在前端做 3 天内即将到期且未完成的二次过滤
      const now = new Date();
      const in3Days = new Date();
      in3Days.setDate(now.getDate() + 3);
      
      tasks.value = res.items.filter(t => {
        if (["COMPLETED", "CANCELLED", "ARCHIVED"].includes(t.status)) return false;
        const end = new Date(t.plannedEndAt);
        return end >= now && end <= in3Days;
      });
      totalTasks.value = tasks.value.length;
    } else {
      tasks.value = res.items;
      totalTasks.value = res.total;
    }
  } catch (err: any) {
    errorMsg.value = err.message || "拉取测试任务列表发生故障";
  } finally {
    loading.value = false;
  }
};

// 获取我自己的 User ID
let cachedMyUserId = "";
const getMyUserId = async (): Promise<string> => {
  if (cachedMyUserId) return cachedMyUserId;
  try {
    const me: any = await apiClient.get("/api/v1/auth/me", (data) => data);
    cachedMyUserId = me.id;
    return cachedMyUserId;
  } catch {
    return "";
  }
};

// 抓取项目内所有版本及项目成员以备筛选及表单
const fetchVersionsAndMembers = async () => {
  try {
    const [vList, mList] = await Promise.all([
      versionsApi.list(projectId.value, { limit: 100 }),
      apiClient.get(`/api/v1/projects/${projectId.value}/members`, (data) => data as Member[])
    ]);
    versions.value = vList.items.filter(v => v.status !== "ARCHIVED");
    members.value = mList;
  } catch (e) {
    console.error("加载关联过滤选项失败", e);
  }
};

// 获取工作台摘要
const fetchSummary = async () => {
  summaryLoading.value = true;
  try {
    summaryData.value = await testTasksApi.mySummary(projectId.value);
  } catch (e) {
    console.error("获取工作台摘要失败", e);
  } finally {
    summaryLoading.value = false;
  }
};

// 归档和恢复
const archiveTask = async (task: TestTask) => {
  if (!confirm(`确定要将任务 [${task.taskNo}] 归档吗？归档后为只读状态。`)) return;
  try {
    await testTasksApi.transition(projectId.value, task.id, {
      targetStatus: "ARCHIVED",
      rowVersion: task.rowVersion
    });
    alert("归档成功");
    fetchTasks();
    fetchSummary();
  } catch (e: any) {
    alert(e.message || "归档失败");
  }
};

const restoreTask = async (task: TestTask) => {
  const reason = prompt("请输入恢复激活归档任务的原因：", "再次重新分析此任务");
  if (reason === null) return;
  if (!reason.trim()) {
    alert("必须填写恢复原因");
    return;
  }
  try {
    await testTasksApi.transition(projectId.value, task.id, {
      targetStatus: "previous_status",
      reasonText: reason,
      rowVersion: task.rowVersion
    });
    alert("恢复成功");
    fetchTasks();
    fetchSummary();
  } catch (e: any) {
    alert(e.message || "恢复失败");
  }
};

// 筛选控制辅助
const toggleSortOrder = () => {
  filters.sortOrder = filters.sortOrder === "asc" ? "desc" : "asc";
  fetchTasks();
};

const resetFilters = () => {
  filters.q = "";
  filters.versionId = "";
  filters.taskType = "";
  filters.status = "";
  filters.ownerId = "";
  filters.sortBy = "updated_at";
  filters.sortOrder = "desc";
  activeQuickFilter.value = "";
  currentPage.value = 1;
  fetchTasks();
};

const changePage = (page: number) => {
  if (page < 1 || page > totalPages.value) return;
  currentPage.value = page;
  fetchTasks();
};

// 新建抽屉显示状态
const createDrawerVisible = ref(false);
const openCreateDrawer = () => {
  createDrawerVisible.value = true;
};
const closeCreateDrawer = () => {
  createDrawerVisible.value = false;
};
const onTaskCreated = () => {
  closeCreateDrawer();
  fetchTasks();
  fetchSummary();
};

// 辅助格式化
const formatStatus = (s: string) => {
  const statusMap: Record<string, string> = {
    DRAFT: "草稿",
    READY: "待开始",
    IN_PROGRESS: "进行中",
    BLOCKED: "已阻塞",
    COMPLETED: "已完成",
    CANCELLED: "已取消",
    ARCHIVED: "已归档"
  };
  return statusMap[s] || s;
};

const formatPriority = (p: string) => {
  const priorityMap: Record<string, string> = {
    LOW: "低",
    MEDIUM: "中",
    HIGH: "高",
    URGENT: "紧急"
  };
  return priorityMap[p] || p;
};

const formatDateShort = (dtStr: string) => {
  if (!dtStr) return "-";
  const d = new Date(dtStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
};

// 挂载加载
onMounted(() => {
  syncFiltersFromQuery();
  fetchVersionsAndMembers();
  fetchTasks();
  fetchSummary();
});

// 监听路由参数变化，处理刷新或回退
watch(() => route.query, () => {
  syncFiltersFromQuery();
  fetchTasks();
});
</script>

<style scoped>
.tasks-page {
  padding: 24px;
  color: #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title-section h1 {
  font-size: 26px;
  font-weight: 700;
  background: linear-gradient(135deg, #a5b4fc 0%, #c084fc 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0 0 6px 0;
}

.subtitle {
  color: #94a3b8;
  font-size: 14px;
  margin: 0;
}

/* 按钮及炫彩发光效果 */
.btn {
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-primary {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.btn-glow {
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}

.btn-glow:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
}

.btn-secondary {
  background: rgba(30, 41, 59, 0.5);
  color: #e2e8f0;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.btn-secondary:hover {
  background: rgba(30, 41, 59, 0.8);
}

/* 汇总面板布局 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.summary-grid-skeleton {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.skeleton-card {
  height: 90px;
  border-radius: 12px;
  background: rgba(30, 41, 59, 0.25);
  animation: pulse 1.5s infinite ease-in-out;
}

.summary-card {
  background: rgba(30, 41, 59, 0.35);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.summary-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.3);
  background: rgba(30, 41, 59, 0.5);
}

.summary-card.active {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.15);
  box-shadow: inset 0 0 10px rgba(99, 102, 241, 0.2);
}

.card-icon {
  font-size: 26px;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 10px;
}

.card-content {
  display: flex;
  flex-direction: column;
}

.card-content .count {
  font-size: 20px;
  font-weight: 700;
  color: #f8fafc;
}

.card-content .count-danger {
  font-size: 20px;
  font-weight: 700;
  color: #f87171;
}

.card-content .count-warning {
  font-size: 20px;
  font-weight: 700;
  color: #fbbf24;
}

.card-content .label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 500;
  margin-top: 2px;
}

/* 过滤控制栏 */
.filter-bar {
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
}

.search-input-wrapper {
  position: relative;
  flex: 1;
  min-width: 260px;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  color: #64748b;
}

.search-input-wrapper input {
  padding-left: 38px;
}

.form-control, .form-select {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: #f1f5f9;
  font-size: 13.5px;
  padding: 8px 12px;
  outline: none;
  width: 100%;
  transition: all 0.2s ease;
}

.form-control:focus, .form-select:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}

.filter-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.filter-controls .form-select {
  width: auto;
  min-width: 130px;
}

.btn-sort {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  font-size: 13.5px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-sort:hover {
  background: rgba(30, 41, 59, 0.9);
  color: #f1f5f9;
}

.btn-reset {
  padding: 8px 16px;
}

/* 列表面板 */
.list-container {
  background: rgba(30, 41, 59, 0.25);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 14px;
  min-height: 350px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.loading-state, .empty-state, .error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 40px;
  text-align: center;
  color: #94a3b8;
  flex: 1;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(99, 102, 241, 0.1);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s infinite linear;
  margin-bottom: 16px;
}

.empty-icon, .error-icon {
  font-size: 44px;
  margin-bottom: 16px;
  filter: drop-shadow(0 0 8px rgba(99, 102, 241, 0.4));
}

.error-icon {
  filter: drop-shadow(0 0 8px rgba(239, 68, 68, 0.4));
}

h3 {
  color: #f1f5f9;
  font-size: 18px;
  margin: 0 0 8px 0;
  font-weight: 600;
}

/* 表格定制 */
.table-responsive {
  width: 100%;
  overflow-x: auto;
}

.tasks-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0 8px;
}

.tasks-table th {
  padding: 12px 16px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.tasks-table td {
  padding: 14px 16px;
  background: rgba(30, 41, 59, 0.35);
  font-size: 13.5px;
  vertical-align: middle;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  transition: all 0.2s ease;
}

.tasks-table td:first-child {
  border-left: 1px solid rgba(255, 255, 255, 0.04);
  border-top-left-radius: 10px;
  border-bottom-left-radius: 10px;
}

.tasks-table td:last-child {
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  border-top-right-radius: 10px;
  border-bottom-right-radius: 10px;
}

.tasks-table tr:hover td {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(99, 102, 241, 0.25);
}

/* 逾期任务整行微红警示 */
.tasks-table tr.overdue-row td {
  background: rgba(239, 68, 68, 0.04);
  border-color: rgba(239, 68, 68, 0.15);
}

.tasks-table tr.overdue-row:hover td {
  background: rgba(239, 68, 68, 0.08);
}

.task-no-link {
  color: #818cf8;
  text-decoration: none;
  font-family: monospace;
  font-weight: 600;
  padding: 2px 6px;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 4px;
}

.task-no-link:hover {
  text-decoration: underline;
  background: rgba(99, 102, 241, 0.2);
}

.task-title-link {
  color: #f1f5f9;
  text-decoration: none;
  font-weight: 500;
}

.task-title-link:hover {
  color: #818cf8;
}

.task-title-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tags-wrapper {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.task-tag {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.blockage-desc {
  font-size: 11.5px;
  color: #f87171;
  background: rgba(239, 68, 68, 0.08);
  padding: 4px 8px;
  border-radius: 6px;
  width: fit-content;
}

/* 勋章微缩样式 */
.type-badge {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11.5px;
  font-weight: 600;
  border-radius: 6px;
}

.type-badge.CASE_DESIGN {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.type-badge.TEST_EXECUTION {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.status-badge {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11.5px;
  font-weight: 600;
  border-radius: 6px;
}

.status-badge.draft { background: rgba(100, 116, 139, 0.15); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.2); }
.status-badge.ready { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.2); }
.status-badge.in_progress { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.2); }
.status-badge.blocked { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.2); }
.status-badge.completed { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.2); }
.status-badge.cancelled { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.2); }
.status-badge.archived { background: rgba(120, 113, 108, 0.15); color: #a8a29e; border: 1px solid rgba(120, 113, 108, 0.2); }

.priority-badge {
  display: inline-block;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
}

.priority-badge.low { background: rgba(255, 255, 255, 0.05); color: #94a3b8; }
.priority-badge.medium { background: rgba(99, 102, 241, 0.1); color: #818cf8; }
.priority-badge.high { background: rgba(245, 158, 11, 0.1); color: #fbbf24; }
.priority-badge.urgent { background: rgba(239, 68, 68, 0.1); color: #f87171; }

.requirement-count-badge {
  background: rgba(255, 255, 255, 0.04);
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 20px;
  color: #cbd5e1;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.date-range {
  display: flex;
  flex-direction: column;
  font-family: monospace;
}

.date-range .split {
  display: none;
}

.date-range .start-date {
  color: #64748b;
  font-size: 11.5px;
}

.date-range .end-date {
  color: #cbd5e1;
  font-weight: 500;
}

.date-range .end-date.danger {
  color: #f87171;
}

.overdue-tag {
  font-size: 9.5px;
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
  font-weight: 600;
}

.text-secondary {
  color: #94a3b8;
}

/* 操作项交互 */
.action-buttons {
  display: flex;
  gap: 8px;
}

.btn-action {
  background: transparent;
  border: none;
  color: #6366f1;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.btn-action:hover {
  background: rgba(99, 102, 241, 0.1);
  color: #818cf8;
}

.btn-action.archive-btn {
  color: #94a3b8;
}

.btn-action.archive-btn:hover {
  background: rgba(148, 163, 184, 0.1);
  color: #cbd5e1;
}

.btn-action.restore-btn {
  color: #10b981;
}

.btn-action.restore-btn:hover {
  background: rgba(16, 185, 129, 0.1);
  color: #34d399;
}

/* 分页条 */
.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  margin-top: 12px;
}

.total-info {
  font-size: 13px;
  color: #64748b;
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-num {
  font-size: 13.5px;
  color: #cbd5e1;
  font-weight: 600;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 0.35; }
}

@media (max-width: 1024px) {
  .summary-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 640px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .filter-controls {
    justify-content: space-between;
  }
}
</style>
