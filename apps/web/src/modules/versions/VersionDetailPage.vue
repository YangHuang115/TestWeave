<template>
  <div class="detail-wrapper" v-if="version">
    <!-- 面包屑导航 -->
    <div class="breadcrumb">
      <router-link :to="`/projects/${projectId}/versions`" class="back-link">
        🏷️ 版本管理
      </router-link>
      <span class="sep">/</span>
      <span class="curr">{{ version.name }}</span>
    </div>

    <!-- 顶栏概览卡片 -->
    <div class="version-hero">
      <div class="hero-left">
        <div class="title-row">
          <h2>{{ version.name }}</h2>
          <span class="version-key">{{ version.key }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-item">
            <span class="label">负责人:</span>
            <span class="val">{{ ownerName }}</span>
          </span>
          <span class="meta-item">
            <span class="label">计划时间:</span>
            <span class="val">{{
              formatDateRange(version.plannedStartAt, version.plannedEndAt)
            }}</span>
          </span>
        </div>
      </div>
      <div class="hero-right">
        <div class="status-box">
          <span class="label">当前状态</span>
          <span :class="['status-badge', version.status.toLowerCase()]">
            {{ formatStatus(version.status) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Tab 标签页切换 -->
    <div class="tabs-nav">
      <button
        v-for="t in tabs"
        :key="t.id"
        :class="['tab-btn', { active: activeTab === t.id, disabled: t.disabled }]"
        @click="void switchTab(t)"
      >
        {{ t.name }}
        <span class="tab-badge" v-if="t.id === 'requirements'">
          {{ requirements.length }}
        </span>
      </button>
    </div>

    <!-- Tab 内容区 -->
    <div class="tab-content">
      <!-- 概览页签 -->
      <div v-if="activeTab === 'overview'" class="overview-tab">
        <div class="info-card">
          <h4>版本描述</h4>
          <p class="desc-text">{{ version.description || "暂无此版本的描述说明。" }}</p>
        </div>
        <div class="info-card">
          <h4>审计记录</h4>
          <p class="audit-hint">
            该版本的创建与变更详情，请前往 [项目设置 > 审计日志] 中查看详细的操作审计 timeline。
          </p>
        </div>
      </div>

      <!-- 需求页签 -->
      <div v-else-if="activeTab === 'requirements'" class="requirements-tab">
        <div class="tab-controls">
          <div class="search-box">
            <span class="icon">🔍</span>
            <input v-model="reqSearchQuery" type="text" placeholder="搜索需求单号或标题..." />
          </div>
          <button
            v-if="projectStore.hasPermission('version.manage') && version.status !== 'ARCHIVED'"
            class="create-btn"
            @click="showCreateReqModal = true"
          >
            + 创建需求
          </button>
        </div>

        <!-- 需求列表表格 -->
        <div v-if="filteredRequirements.length === 0" class="empty-state">
          <span class="icon">📁</span>
          <h3>暂无关联需求</h3>
          <p>当前版本下尚未规划需求条目。</p>
        </div>

        <div v-else class="tree-table-container">
          <div class="tree-table-header">
            <div class="col-no">需求编号</div>
            <div class="col-title">需求标题 (点击进入详情)</div>
            <div class="col-status">外部状态</div>
            <div class="col-progress">测试任务与进度</div>
          </div>

          <div class="tree-table-body">
            <div v-for="req in filteredRequirements" :key="req.id" class="requirement-group">
              <!-- 需求主行 -->
              <div class="req-row">
                <div class="col-no">
                  <button class="toggle-btn" @click="void toggleExpand(req.id)">
                    {{ isExpanded(req.id) ? "▼" : "▶" }}
                  </button>
                  <span class="doc-icon">📄</span>
                  <span class="req-no-text">{{ req.requirement_no }}</span>
                </div>
                <div class="col-title">
                  <router-link
                    :to="`/projects/${projectId}/versions/${versionId}/requirements/${req.id}`"
                    class="req-title-link"
                  >
                    {{ req.title }}
                  </router-link>
                </div>
                <div class="col-status">
                  <span :class="['status-dot', req.status.toLowerCase()]"></span>
                  <span class="status-text">{{ formatReqStatus(req.status) }}</span>
                </div>
                <div class="col-progress">
                  <!-- 显示进度快照 -->
                  <span class="task-summary-badge">
                    {{
                      req.tasks && req.tasks.length > 0
                        ? `${req.tasks.filter((t: TestTask) => t.status === "已解决").length}/${req.tasks.length} 已解决`
                        : "暂无测试任务"
                    }}
                  </span>
                </div>
              </div>

              <!-- 测试任务子列表 (折叠展开) -->
              <div v-if="isExpanded(req.id)" class="tasks-sublist">
                <!-- 有测试任务的情况 -->
                <template v-if="req.tasks && req.tasks.length > 0">
                  <div v-for="task in req.tasks" :key="task.id" class="task-row">
                    <div class="col-no indent">
                      <span class="task-icon">{{ task.type === "用例" ? "📝" : "▶️" }}</span>
                      <span class="task-type-badge">{{
                        task.type === "用例" ? "用例设计" : "测试执行"
                      }}</span>
                    </div>
                    <div class="col-title task-name">
                      <router-link
                        :to="`/projects/${projectId}/test-tasks/${task.id}`"
                        class="task-title-link"
                      >
                        {{ task.name }}
                      </router-link>
                    </div>
                    <div class="col-status">
                      <span :class="['task-status-badge', task.status.toLowerCase()]">
                        {{ task.status }}
                      </span>
                    </div>
                    <div class="col-progress task-metrics">
                      <span class="owner">{{ task.owner }}</span>
                      <span class="metrics">{{ task.progress }}</span>
                      <div class="progress-bar-bg">
                        <div class="progress-bar-fill" :style="{ width: task.percent + '%' }"></div>
                      </div>
                    </div>
                  </div>
                  <div class="task-row add-task-row">
                    <div class="col-no indent"></div>
                    <div class="col-title"></div>
                    <div class="col-status"></div>
                    <div class="col-progress text-right">
                      <button
                        class="create-task-btn inline-btn"
                        @click.stop="openCreateTaskDrawer(req.id)"
                      >
                        + 创建测试任务
                      </button>
                    </div>
                  </div>
                </template>
                <!-- 无测试任务的情况 -->
                <template v-else>
                  <div class="task-row empty-task-row">
                    <div class="col-no indent">
                      <span class="empty-icon">📭</span>
                      <span class="empty-text">暂无测试任务</span>
                    </div>
                    <div class="col-title"></div>
                    <div class="col-status"></div>
                    <div class="col-progress text-right">
                      <button class="create-task-btn" @click.stop="openCreateTaskDrawer(req.id)">
                        + 创建测试任务
                      </button>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建需求弹窗 (Modal) -->
    <div v-if="showCreateReqModal" class="modal-overlay" @click.self="showCreateReqModal = false">
      <div class="modal-card">
        <h3>创建新需求</h3>
        <p class="subtitle">在当前版本中新建一条正式的需求条目。</p>
        <form @submit.prevent="void handleCreateRequirement()">
          <!-- 需求单号完全由系统自动生成，移除手动输入以防重复与不规则 -->

          <div class="form-group">
            <label for="req-title">需求标题 *</label>
            <input
              id="req-title"
              v-model="newReqForm.title"
              type="text"
              required
              placeholder="请输入清晰的需求名称"
              :disabled="isCreatingReq"
            />
          </div>

          <div class="form-group">
            <label for="req-priority">优先级 *</label>
            <select
              id="req-priority"
              v-model="newReqForm.priority"
              required
              :disabled="isCreatingReq"
            >
              <option value="HIGH">高</option>
              <option value="MEDIUM">中</option>
              <option value="LOW">低</option>
            </select>
          </div>

          <div class="form-group">
            <label for="req-owner">负责人</label>
            <select id="req-owner" v-model="newReqForm.owner_id" :disabled="isCreatingReq">
              <option value="">未分配</option>
              <option v-for="m in members" :key="m.user_id" :value="m.user_id">
                {{ m.display_name }} ({{ m.username }})
              </option>
            </select>
          </div>

          <div class="form-group">
            <label for="req-desc">需求描述</label>
            <textarea
              id="req-desc"
              v-model="newReqForm.description"
              placeholder="请输入需求详细业务逻辑..."
              :disabled="isCreatingReq"
            ></textarea>
          </div>

          <div v-if="createReqError" class="error-banner">⚠️ {{ createReqError }}</div>

          <div class="modal-actions">
            <button
              type="button"
              class="cancel-btn"
              :disabled="isCreatingReq"
              @click="showCreateReqModal = false"
            >
              取消
            </button>
            <button type="submit" class="submit-btn" :disabled="isCreatingReq">
              {{ isCreatingReq ? "正在创建..." : "确认创建" }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 创建测试任务抽屉 Component -->
    <CreateTaskDrawer
      v-if="showCreateTaskDrawer"
      :project-id="projectId"
      :versions="allVersions"
      :members="members"
      :default-version-id="versionId"
      :default-requirement-id="createTaskDefaultReqId"
      @close="showCreateTaskDrawer = false"
      @created="handleTaskCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed } from "vue";
import { useRoute } from "vue-router";
import { useProjectStore } from "../../shared/stores/project";
import { useAuthStore } from "../../shared/stores/auth";
import { versionsApi, type Version } from "./api";
import { apiClient } from "../../shared/api/client";
import CreateTaskDrawer from "../tasks/CreateTaskDrawer.vue";

interface Member {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
}

interface ApiTestTask {
  id: string;
  taskType: string;
  title: string;
  status: string;
  ownerName?: string;
  completionCount?: number;
  requirementId?: string;
}

interface TestTask {
  id: string;
  type: string;
  name: string;
  status: string;
  owner: string;
  progress: string;
  percent: number;
}

interface Requirement {
  id: string;
  requirement_no: string;
  title: string;
  status: string;
  priority: string;
  tasks: TestTask[];
}

interface TabItem {
  id: string;
  name: string;
  disabled?: boolean;
}

const route = useRoute();
const projectStore = useProjectStore();
const authStore = useAuthStore();
const projectId = route.params.projectId as string;
const versionId = route.params.versionId as string;

// 数据
const version = ref<Version | null>(null);
const members = ref<Member[]>([]);
const requirements = ref<Requirement[]>([]);
const activeTab = ref("requirements");

// 新建任务抽屉状态
const showCreateTaskDrawer = ref(false);
const createTaskDefaultReqId = ref("");
const allVersions = ref<Version[]>([]);

const tabs: TabItem[] = [
  { id: "overview", name: "概览" },
  { id: "requirements", name: "需求范围" },
  { id: "tasks", name: "测试任务 (未接入)", disabled: true },
  { id: "coverage", name: "覆盖情况 (未接入)", disabled: true },
  { id: "defects", name: "缺陷 (未接入)", disabled: true },
];

const ownerName = computed(() => {
  if (!version.value) return "";
  const m = members.value.find((x) => x.user_id === version.value?.ownerId);
  return m ? m.display_name : "未分配";
});

// 折叠展开控制
const expandedReqs = ref<Set<string>>(new Set());
function toggleExpand(reqId: string) {
  if (expandedReqs.value.has(reqId)) {
    expandedReqs.value.delete(reqId);
  } else {
    expandedReqs.value.add(reqId);
  }
}
function isExpanded(reqId: string) {
  return expandedReqs.value.has(reqId);
}

// 需求检索
const reqSearchQuery = ref("");
const filteredRequirements = computed(() => {
  if (!reqSearchQuery.value) return requirements.value;
  const q = reqSearchQuery.value.toLowerCase();
  return requirements.value.filter(
    (x) => x.requirement_no.toLowerCase().includes(q) || x.title.toLowerCase().includes(q),
  );
});

// 格式化函数
function formatStatus(status: string) {
  const mapping: Record<string, string> = {
    PLANNING: "规划中",
    ACTIVE: "进行中",
    TESTING: "测试中",
    RELEASED: "已发布",
    ARCHIVED: "已归档",
  };
  return mapping[status] || status;
}

function formatReqStatus(status: string) {
  const mapping: Record<string, string> = {
    DRAFT: "草稿",
    READY: "待测试分析",
    CANCELLED: "已取消",
    ARCHIVED: "已归档",
    IN_PROGRESS: "进行中",
    RESOLVED: "已解决",
    SCHEDULED: "已排期",
  };
  return mapping[status] || status;
}

function formatDateRange(start: string | null, end: string | null) {
  if (!start && !end) return "未设置计划时间";
  const s = start ? start.substring(0, 10) : "未设置";
  const e = end ? end.substring(0, 10) : "未设置";
  return `${s} ~ ${e}`;
}

function switchTab(t: TabItem) {
  if (t.disabled) return;
  activeTab.value = t.id;
}

function formatTask(t: ApiTestTask): TestTask {
  const typeMap: Record<string, string> = {
    CASE_DESIGN: "用例",
    TEST_EXECUTION: "执行",
  };
  const statusMap: Record<string, string> = {
    DRAFT: "草稿",
    READY: "就绪",
    IN_PROGRESS: "进行中",
    BLOCKED: "已阻塞",
    COMPLETED: "已完成",
    CANCELLED: "已取消",
    ARCHIVED: "已归档",
  };

  let progressText = "0 / 10";
  let percent = 0;
  if (t.status === "COMPLETED") {
    progressText = "已完成";
    percent = 100;
  } else if (t.status === "IN_PROGRESS") {
    progressText = `${t.completionCount || 0} 已完成`;
    percent = t.completionCount ? Math.min(Math.round((t.completionCount / 10) * 100), 99) : 30;
  } else {
    progressText = t.status === "CANCELLED" ? "已取消" : "未开始";
    percent = 0;
  }

  return {
    id: t.id,
    type: typeMap[t.taskType] || "用例",
    name: t.title,
    status: statusMap[t.status] || t.status,
    owner: t.ownerName || "未分配",
    progress: progressText,
    percent: percent,
  };
}

async function loadRequirements() {
  try {
    const data = await apiClient.get(
      `/api/v1/projects/${projectId}/versions/${versionId}/requirements`,
      (val) => val as Requirement[],
    );

    // 获取该版本下所有关联的测试任务
    let allTasks: ApiTestTask[] = [];
    try {
      const taskRes = await apiClient.get(
        `/api/v1/projects/${projectId}/test-tasks?versionId=${versionId}&limit=1000`,
        (val) => val as { items: ApiTestTask[]; total: number },
      );
      allTasks = taskRes.items || [];
    } catch (err) {
      console.warn("加载测试任务接口失败，使用空列表", err);
    }

    requirements.value = data.map((r) => ({
      ...r,
      // 将真实的测试任务注入对应的需求
      tasks: allTasks.filter((t) => t.requirementId === r.id).map(formatTask),
    }));

    // 默认展开所有需求
    expandedReqs.value = new Set(requirements.value.map((x) => x.id));
  } catch (e: unknown) {
    const err = e as { status?: number };
    console.warn("未检测到后端需求接口，使用 mock 数据渲染", err.status);
    requirements.value = [
      {
        id: "mock-1",
        requirement_no: "REQ-1001",
        title: "用户登录需求",
        status: "IN_PROGRESS",
        priority: "HIGH",
        tasks: [
          {
            id: "t1-1",
            type: "用例",
            name: "用例设计任务: 登录场景覆盖",
            status: "待处理",
            owner: "张三",
            progress: "0 / 12",
            percent: 0,
          },
          {
            id: "t1-2",
            type: "执行",
            name: "测试执行任务: 登录回归",
            status: "未开始",
            owner: "李四",
            progress: "0 / 24",
            percent: 0,
          },
        ],
      },
      {
        id: "mock-2",
        requirement_no: "REQ-1002",
        title: "商品搜索需求",
        status: "RESOLVED",
        priority: "HIGH",
        tasks: [
          {
            id: "t2-1",
            type: "用例",
            name: "用例设计任务: 搜索测试点",
            status: "进行中",
            owner: "王五",
            progress: "6 / 10",
            percent: 60,
          },
        ],
      },
      {
        id: "mock-3",
        requirement_no: "REQ-1003",
        title: "购物车需求",
        status: "SCHEDULED",
        priority: "MEDIUM",
        tasks: [],
      },
    ];
    expandedReqs.value = new Set(requirements.value.map((x) => x.id));
  }
}

// 加载核心数据
async function loadData() {
  try {
    const data = await apiClient.get(
      `/api/v1/projects/${projectId}/members`,
      (val) => val as Member[],
    );
    members.value = data;

    version.value = await versionsApi.get(projectId, versionId);

    // 缓存最后一次访问的版本记录
    const userId = authStore.currentUser?.id;
    if (userId && projectId && versionId) {
      localStorage.setItem(`last_version:${userId}:${projectId}`, versionId);
    }

    // 加载全部版本
    const vRes = await versionsApi.list(projectId);
    allVersions.value = vRes.items || [];

    await loadRequirements();
  } catch (e: unknown) {
    const err = e as { message?: string };
    console.error("加载数据失败", err.message);
  }
}

function openCreateTaskDrawer(reqId: string) {
  createTaskDefaultReqId.value = reqId;
  showCreateTaskDrawer.value = true;
}

function handleTaskCreated() {
  showCreateTaskDrawer.value = false;
  void loadRequirements();
}

// 创建需求相关
const showCreateReqModal = ref(false);
const isCreatingReq = ref(false);
const createReqError = ref<string | null>(null);
const newReqForm = reactive({
  title: "",
  priority: "MEDIUM",
  owner_id: "",
  description: "",
});

async function handleCreateRequirement() {
  isCreatingReq.value = true;
  createReqError.value = null;
  try {
    const payload = {
      requirement_no: undefined,
      title: newReqForm.title,
      priority: newReqForm.priority,
      owner_id: newReqForm.owner_id || undefined,
      description: newReqForm.description,
    };
    await apiClient.post(
      `/api/v1/projects/${projectId}/versions/${versionId}/requirements`,
      (data) => data,
      payload,
    );
    showCreateReqModal.value = false;
    void loadRequirements();
  } catch (e: unknown) {
    const err = e as { status?: number; message?: string };
    if (err.status === 404) {
      requirements.value.push({
        id: `mock-${Date.now()}`,
        requirement_no: "系统将自动生成",
        title: newReqForm.title,
        status: "DRAFT",
        priority: newReqForm.priority,
        tasks: [],
      });
      showCreateReqModal.value = false;
    } else {
      createReqError.value = err.message || "创建需求失败";
    }
  } finally {
    isCreatingReq.value = false;
  }
}

onMounted(() => {
  void loadData();
});
</script>

<style scoped>
.detail-wrapper {
  padding: 24px;
  color: #f1f5f9;
}

.breadcrumb {
  margin-bottom: 20px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.back-link {
  color: #94a3b8;
  text-decoration: none;
  transition: color 0.2s;
}

.back-link:hover {
  color: #6366f1;
}

.breadcrumb .sep {
  color: rgba(255, 255, 255, 0.2);
}

.breadcrumb .curr {
  color: #f1f5f9;
  font-weight: 500;
}

.version-hero {
  background: rgba(30, 41, 59, 0.3);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
}

.hero-left {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-row h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.version-key {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  font-family: monospace;
}

.meta-row {
  display: flex;
  gap: 24px;
}

.meta-item {
  font-size: 13.5px;
}

.meta-item .label {
  color: #64748b;
  margin-right: 6px;
}

.meta-item .val {
  color: #cbd5e1;
}

.status-box {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.status-box .label {
  font-size: 11px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-badge {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.status-badge.planning {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

.status-badge.active {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}

.status-badge.testing {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.status-badge.released {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.status-badge.archived {
  background: rgba(100, 116, 139, 0.15);
  color: #64748b;
}

/* Tabs */
.tabs-nav {
  display: flex;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 24px;
  gap: 8px;
}

.tab-btn {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #94a3b8;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-btn:hover:not(.disabled) {
  color: #f1f5f9;
}

.tab-btn.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
}

.tab-btn.disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.tab-badge {
  background: rgba(255, 255, 255, 0.1);
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  color: #cbd5e1;
}

.tab-content {
  min-height: 300px;
}

/* 概览页签 */
.overview-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-card {
  background: rgba(30, 41, 59, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 20px;
}

.info-card h4 {
  margin: 0 0 12px;
  font-size: 15px;
  color: #94a3b8;
  border-left: 3px solid #6366f1;
  padding-left: 10px;
}

.desc-text {
  font-size: 14px;
  line-height: 1.6;
  color: #cbd5e1;
  margin: 0;
  white-space: pre-wrap;
}

.audit-hint {
  font-size: 13.5px;
  color: #94a3b8;
  margin: 0;
}

/* 需求列表页签 */
.tab-controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.tab-controls .search-box {
  position: relative;
  width: 100%;
  max-width: 320px;
}

.tab-controls .search-box input {
  width: 100%;
  padding: 8px 12px 8px 34px;
  background: rgba(30, 41, 59, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f1f5f9;
  font-size: 13.5px;
}

.tab-controls .search-box .icon {
  position: absolute;
  left: 10px;
  top: 9px;
  font-size: 13px;
  opacity: 0.5;
}

.tab-controls .create-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  color: #ffffff;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
}

/* 树状表格 (符合设计图) */
.tree-table-container {
  background: rgba(30, 41, 59, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  overflow: hidden;
}

.tree-table-header {
  display: flex;
  background: rgba(15, 23, 42, 0.4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 12px 20px;
  font-weight: 600;
  color: #94a3b8;
  font-size: 13.5px;
}

.col-no {
  width: 15%;
  display: flex;
  align-items: center;
  gap: 6px;
}

.col-title {
  width: 45%;
}

.col-status {
  width: 15%;
}

.col-progress {
  width: 25%;
}

.requirement-group {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.req-row {
  display: flex;
  padding: 16px 20px;
  align-items: center;
  font-size: 14px;
}

.req-row:hover {
  background: rgba(255, 255, 255, 0.01);
}

.toggle-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 10px;
  cursor: pointer;
  padding: 4px;
  display: inline-flex;
  align-items: center;
}

.doc-icon {
  color: #6366f1;
}

.req-no-text {
  font-weight: 600;
  font-family: monospace;
}

.req-title-link {
  color: #f1f5f9;
  text-decoration: none;
  font-weight: 500;
}

.req-title-link:hover {
  color: #6366f1;
  text-decoration: underline;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 8px;
}

.status-dot.in_progress {
  background: #3b82f6;
}

.status-dot.resolved {
  background: #10b981;
}

.status-dot.scheduled {
  background: #f59e0b;
}

.status-dot.draft {
  background: #94a3b8;
}

.status-text {
  font-size: 13px;
  color: #cbd5e1;
}

.task-summary-badge {
  font-size: 12px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.03);
  padding: 2px 8px;
  border-radius: 12px;
}

/* 测试任务子列表样式 */
.tasks-sublist {
  background: rgba(15, 23, 42, 0.15);
  border-top: 1px solid rgba(255, 255, 255, 0.03);
  padding: 4px 0;
}

.task-row {
  display: flex;
  padding: 12px 20px;
  align-items: center;
  font-size: 13px;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.02);
}

.task-row:last-child {
  border-bottom: none;
}

.indent {
  padding-left: 28px;
}

.task-icon {
  margin-right: 6px;
}

.task-type-badge {
  background: rgba(255, 255, 255, 0.04);
  color: #94a3b8;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.task-name {
  color: #94a3b8;
}

.task-status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}

.task-status-badge.待处理 {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.task-status-badge.未开始 {
  background: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
}

.task-status-badge.进行中 {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.task-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
}

.task-metrics .owner {
  color: #94a3b8;
  min-width: 48px;
}

.task-metrics .metrics {
  color: #cbd5e1;
  font-family: monospace;
}

.progress-bar-bg {
  width: 80px;
  height: 6px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 3px;
}

/* 空测试任务占位 (含创建任务按钮) */
.empty-task-row {
  color: #64748b;
}

.task-title-link {
  color: #cbd5e1;
  text-decoration: none;
  transition: color 0.2s ease;
}

.task-title-link:hover {
  color: #6366f1;
}

.empty-task-row .empty-icon {
  margin-right: 6px;
}

.empty-task-row .empty-text {
  font-size: 12.5px;
}

.create-task-btn {
  background: transparent;
  border: 1px dashed rgba(255, 255, 255, 0.1);
  color: #64748b;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.create-task-btn:hover {
  border-color: rgba(99, 102, 241, 0.4);
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.05);
}

.text-right {
  display: flex;
  justify-content: flex-end;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-card {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 28px;
  max-width: 520px;
  width: 90%;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.modal-card h3 {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 600;
}

.modal-card .subtitle {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 24px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
}

.form-group input,
.form-group select,
.form-group textarea {
  padding: 10px;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
}

.form-group textarea {
  height: 80px;
  resize: vertical;
}

.form-group .hint {
  font-size: 12px;
  color: #64748b;
}

.error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 10px;
  border-radius: 6px;
  color: #f87171;
  font-size: 13px;
  margin-bottom: 16px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.modal-actions button {
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.modal-actions .cancel-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
}

.modal-actions .submit-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  color: #ffffff;
  border: none;
}

/* 状态加载样式 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  border: 1px dashed rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  text-align: center;
  padding: 30px;
}

.empty-state h3 {
  margin: 12px 0 6px;
  font-size: 15px;
}

.empty-state p {
  color: #64748b;
  font-size: 13px;
  margin: 0;
}
</style>
