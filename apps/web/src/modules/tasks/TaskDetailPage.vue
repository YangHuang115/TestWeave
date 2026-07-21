<template>
  <div class="task-detail-page" v-if="task">
    <!-- 面包屑导航与状态顶栏 -->
    <div class="detail-header">
      <div class="breadcrumb">
        <router-link :to="`/projects/${projectId}/test-tasks`" class="back-link">
          ← 返回任务列表
        </router-link>
        <span class="divider">/</span>
        <span class="task-no">{{ task.taskNo }}</span>
      </div>

      <div class="workflow-actions-bar">
        <!-- 任务状态展示 -->
        <span class="status-badge" :class="task.status.toLowerCase()">
          当前状态: {{ formatStatus(task.status) }}
        </span>

        <!-- 状态流转操作按钮组 -->
        <div class="transition-buttons">
          <!-- DRAFT -> READY -->
          <button
            v-if="task.status === 'DRAFT'"
            class="btn btn-primary btn-glow"
            @click="handleTransition('READY')"
          >
            提交至待开始 (READY)
          </button>

          <!-- READY -> IN_PROGRESS -->
          <button
            v-if="task.status === 'READY'"
            class="btn btn-indigo"
            @click="handleTransition('IN_PROGRESS')"
          >
            开始执行 (IN_PROGRESS)
          </button>

          <!-- IN_PROGRESS -> COMPLETED / BLOCKED / CANCELLED -->
          <template v-if="task.status === 'IN_PROGRESS'">
            <button class="btn btn-emerald" @click="openTransitionModal('COMPLETED')">
              完成任务 (COMPLETED)
            </button>
            <button class="btn btn-red" @click="openTransitionModal('BLOCKED')">
              设置阻塞 (BLOCKED)
            </button>
            <button class="btn btn-secondary" @click="openTransitionModal('CANCELLED')">
              取消任务
            </button>
          </template>

          <!-- BLOCKED -> RESOLVE -->
          <button
            v-if="task.status === 'BLOCKED'"
            class="btn btn-indigo"
            @click="openTransitionModal('UNBLOCK')"
          >
            解除阻塞 (IN_PROGRESS)
          </button>

          <!-- COMPLETED -> REOPEN / ARCHIVE -->
          <template v-if="task.status === 'COMPLETED'">
            <button class="btn btn-warning" @click="openTransitionModal('REOPEN')">
              重新打开 (IN_PROGRESS)
            </button>
            <button class="btn btn-secondary" @click="archiveTask">归档 (ARCHIVED)</button>
          </template>

          <!-- CANCELLED -> RESTORE / ARCHIVE -->
          <template v-if="task.status === 'CANCELLED'">
            <button class="btn btn-indigo" @click="openTransitionModal('RESTORE_CANCEL')">
              恢复为草稿 (DRAFT)
            </button>
            <button class="btn btn-secondary" @click="archiveTask">归档 (ARCHIVED)</button>
          </template>

          <!-- ARCHIVED -> RESTORE -->
          <button
            v-if="task.status === 'ARCHIVED'"
            class="btn btn-emerald"
            @click="restoreArchived"
          >
            激活恢复任务
          </button>
        </div>
      </div>
    </div>

    <!-- 核心布局：左侧宽阔主体表单，右侧操作控制中心 -->
    <div class="detail-layout">
      <!-- 左侧基础信息编辑主面板 (75% 宽度) -->
      <div class="card info-card">
        <div class="card-header">
          <h3>任务基础属性</h3>
          <span class="read-only-badge" v-if="isReadOnly">只读模式</span>
        </div>

        <form @submit.prevent="updateTaskInfo" class="info-form">
          <!-- 任务标题 -->
          <div class="form-group">
            <label class="required">任务标题</label>
            <input
              type="text"
              v-model="editForm.title"
              class="form-control"
              :disabled="isReadOnly"
              required
            />
          </div>

          <!-- 任务描述 -->
          <div class="form-group">
            <label>任务描述</label>
            <textarea
              v-model="editForm.description"
              rows="3"
              class="form-control textarea"
              :disabled="isReadOnly"
            ></textarea>
          </div>

          <!-- 三列网格：负责人、优先级、计划时间范围 -->
          <div class="form-grid-3">
            <div class="form-group">
              <label>负责人</label>
              <select v-model="editForm.ownerId" class="form-select" :disabled="isReadOnly">
                <option v-for="m in members" :key="m.user_id" :value="m.user_id">
                  {{ m.display_name }}
                </option>
              </select>
            </div>

            <div class="form-group">
              <label>任务优先级</label>
              <select v-model="editForm.priority" class="form-select" :disabled="isReadOnly">
                <option value="LOW">低 (LOW)</option>
                <option value="MEDIUM">中 (MEDIUM)</option>
                <option value="HIGH">高 (HIGH)</option>
                <option value="URGENT">紧急 (URGENT)</option>
              </select>
            </div>

            <div class="form-group">
              <label>计划时间</label>
              <div class="date-range-inputs">
                <input
                  type="datetime-local"
                  v-model="editForm.plannedStartAt"
                  class="form-control"
                  :disabled="isReadOnly"
                />
                <span class="range-sep">至</span>
                <input
                  type="datetime-local"
                  v-model="editForm.plannedEndAt"
                  class="form-control"
                  :disabled="isReadOnly"
                />
              </div>
            </div>
          </div>

          <!-- 双列网格：标签与覆盖需求 -->
          <div class="form-grid-2">
            <div class="form-group">
              <label>标签</label>
              <div class="tags-input-box" :class="{ disabled: isReadOnly }">
                <span v-for="t in editForm.tagsJson" :key="t" class="form-tag">
                  {{ t }}
                  <span v-if="!isReadOnly" class="tag-del" @click="removeTag(t)">×</span>
                </span>
                <input
                  v-if="!isReadOnly"
                  type="text"
                  v-model="newTag"
                  placeholder="+标签..."
                  @keydown.enter.prevent="addTag"
                />
              </div>
            </div>

            <div class="form-group">
              <label>覆盖需求</label>
              <div class="linked-requirement-display">
                <div class="req-content" v-if="linkedRequirements.length > 0">
                  <span class="req-badge">
                    {{ linkedRequirements[0].requirement_no || linkedRequirements[0].requirementNo }}
                  </span>
                  <span class="req-title">{{ linkedRequirements[0].title }}</span>
                </div>
                <span class="no-req" v-else>暂无关联需求，READY 状态前需进行关联。</span>
                <button
                  v-if="!isReadOnly"
                  type="button"
                  class="btn-link-req"
                  @click="openLinkReqModal"
                >
                  配置关联需求
                </button>
              </div>
            </div>
          </div>

          <!-- 用例设计任务特有字段 -->
          <template v-if="task.taskType === 'CASE_DESIGN'">
            <div class="form-group">
              <label>设计测试目标</label>
              <textarea
                v-model="editForm.testGoal"
                rows="2"
                class="form-control textarea"
                :disabled="isReadOnly"
              ></textarea>
            </div>
            <div class="form-group">
              <label>排除测试范围</label>
              <textarea
                v-model="editForm.excludedScope"
                rows="2"
                class="form-control textarea"
                :disabled="isReadOnly"
              ></textarea>
            </div>
          </template>

          <!-- 额外时间元数据，彻底移除了完成次数！ -->
          <div class="metadata-section">
            <div class="meta-item" v-if="task.actualStartedAt">
              <span class="meta-label">实际启动:</span>
              <span class="meta-value">{{ formatDatetime(task.actualStartedAt) }}</span>
            </div>
            <div class="meta-item" v-if="task.currentCompletedAt">
              <span class="meta-label">完成时间:</span>
              <span class="meta-value">{{ formatDatetime(task.currentCompletedAt) }}</span>
            </div>
          </div>

          <button
            v-if="!isReadOnly"
            type="submit"
            class="btn btn-primary btn-glow"
            :disabled="updating"
          >
            {{ updating ? "正在保存..." : "保存基础信息修改" }}
          </button>
        </form>
      </div>

      <!-- 右侧动作控制中心与辅助页签 (25% 宽度) -->
      <div class="action-console-panel">
        <!-- 核心直达卡片面板 -->
        <div class="card console-card">
          <div class="card-header">
            <h3>测试设计控制台</h3>
          </div>
          <div class="console-body">
            <!-- 用例编写大卡片 -->
            <div class="action-card edit-cases" @click="goToCaseWriting">
              <div class="card-icon">📊</div>
              <div class="card-info">
                <h4>用例编写</h4>
                <p>进入多用例在线电子表格，点击单元格直接编写与发布步骤。</p>
              </div>
              <span class="go-arrow">→</span>
            </div>

            <!-- 脑图设计大卡片 -->
            <div class="action-card mindmap" @click="goToMindmap">
              <div class="card-icon">🧠</div>
              <div class="card-info">
                <h4>脑图设计</h4>
                <p>通过多层可视化分支梳理测试点并双向生成用例，体验 ProcessOn 级交互。</p>
              </div>
              <span class="go-arrow">→</span>
            </div>

            <!-- AI用例设计大卡片 -->
            <div class="action-card ai-design" @click="activeConsoleTab('ai')">
              <div class="card-icon">✨</div>
              <div class="card-info">
                <h4>AI 用例生成</h4>
                <p>启动 M12 大模型算力，智能拆解需求测试树并一键生成候选用例。</p>
              </div>
              <span class="go-arrow">→</span>
            </div>
          </div>
        </div>

        <!-- 辅助页签容器：展示流转与 AI 生成 -->
        <div class="tab-container">
          <div class="tab-headers">
            <button
              class="tab-header-btn"
              :class="{ active: currentTab === 'activities' }"
              @click="currentTab = 'activities'"
            >
              🕒 状态流转历史
            </button>
            <button
              class="tab-header-btn"
              :class="{ active: currentTab === 'ai' }"
              @click="currentTab = 'ai'"
            >
              🔮 AI 运行状态
            </button>
          </div>

          <div class="tab-body">
            <!-- 页签 1: 状态历史与活动 -->
            <div v-if="currentTab === 'activities'" class="tab-pane">
              <div class="activities-timeline" v-if="activities.length > 0">
                <div v-for="a in activities" :key="a.id" class="timeline-node">
                  <div class="node-time">{{ formatDatetime(a.createdAt) }}</div>
                  <div class="node-content">
                    <div class="node-title">
                      <span class="node-actor">{{ a.actorName || "系统" }}</span>:
                      <span class="node-flow"
                        >{{ formatStatus(a.fromStatus) }} → {{ formatStatus(a.toStatus) }}</span
                      >
                    </div>
                    <div class="node-details" v-if="a.reasonCode || a.reasonText">
                      <p class="reason-text" v-if="a.reasonText">💬 "{{ a.reasonText }}"</p>
                    </div>
                  </div>
                </div>
              </div>
              <div class="empty-list" v-else>
                <p>暂无活动流转记录。</p>
              </div>
            </div>

            <!-- 页签 2: AI 进度占位 -->
            <div v-if="currentTab === 'ai'" class="tab-pane">
              <div class="ai-glow-card">
                <div class="ai-glow-header">
                  <span class="ai-sparkle">✨</span>
                  <h4>AI 智能推荐就绪</h4>
                </div>
                <p class="ai-desc">
                  已与 M12/M13 算力平台打通。等待导入正式测试需求或脑图树大纲分析即可激活用例生成。
                </p>

                <div class="ai-scanning-animation">
                  <div class="scanner-bar"></div>
                  <div class="grid-mesh"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 流转操作模态框 -->
    <div class="modal-overlay" v-if="transitionModalVisible" @click.self="closeTransitionModal">
      <div class="modal-content">
        <div class="modal-header">
          <h3>{{ getTransitionModalTitle() }}</h3>
          <button class="btn-close" @click="closeTransitionModal">×</button>
        </div>

        <div class="modal-body">
          <div class="form-group" v-if="transForm.reasonRequired">
            <label class="required">请选择/填写流转原因</label>
            <select v-model="transForm.reasonCode" class="form-select">
              <option value="REQUIREMENT_UNCLEAR">需求不明确 (REQUIREMENT_UNCLEAR)</option>
              <option value="ENVIRONMENT_ISSUE">测试环境未就绪 (ENVIRONMENT_ISSUE)</option>
              <option value="CODE_NOT_READY">开发代码未就绪 (CODE_NOT_READY)</option>
              <option value="FORCE_ABORT">项目强制终止 (FORCE_ABORT)</option>
              <option value="OTHER">其他原因 (OTHER)</option>
            </select>
          </div>

          <div class="form-group">
            <label>流转备注与说明</label>
            <textarea
              v-model="transForm.reasonText"
              rows="3"
              placeholder="请输入本次任务状态流转的具体原因或审批意见..."
              class="form-control textarea"
            ></textarea>
          </div>

          <div v-if="transError" class="error-msg">⚠️ {{ transError }}</div>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeTransitionModal" :disabled="transmitting">
            取消
          </button>
          <button
            class="btn btn-primary btn-glow"
            @click="executeTransition"
            :disabled="transmitting"
          >
            {{ transmitting ? "流转中..." : "确定流转状态" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 关联需求配置模态框 -->
    <div class="modal-overlay" v-if="linkReqModalVisible" @click.self="closeLinkReqModal">
      <div class="modal-content link-req-modal">
        <div class="modal-header">
          <h3>配置关联的覆盖需求</h3>
          <button class="btn-close" @click="closeLinkReqModal">×</button>
        </div>

        <div class="modal-body link-req-body">
          <p class="desc-info">
            请勾选该用例设计任务所需要覆盖的需求。已被其他未完成设计任务覆盖的需求会进行黄色警示。
          </p>

          <div class="req-checkbox-list">
            <label
              v-for="r in allRequirements"
              :key="r.id"
              class="checkbox-label-card"
              :class="{ selected: selectedReqId === r.id }"
            >
              <input type="radio" :value="r.id" v-model="selectedReqId" name="task-requirement" />
              <div class="card-req-meta">
                <span class="card-req-no">{{ r.requirement_no || r.requirementNo }}</span>
                <span class="card-req-title">{{ r.title }}</span>
              </div>
            </label>
          </div>

          <!-- 警告展示 -->
          <div v-if="linkWarnings.length > 0" class="info-alert danger-alert">
            ⚠️ <b>需求覆盖冲突警示：</b>
            <ul class="warning-ul">
              <li v-for="w in linkWarnings" :key="w.requirementNo">
                需求 <b>{{ w.requirementNo }}</b> ({{ w.requirementTitle }}) 已被其他进行中设计任务
                <b>{{ w.taskNo }}</b> (负责人: {{ w.ownerName }})
                关联覆盖。继续保存可能导致重复设计！
              </li>
            </ul>
            <div class="warning-actions">
              <button class="btn btn-secondary btn-sm" @click="clearLinkWarnings">返回修改</button>
              <button class="btn class-red btn-sm" @click="persistLinkRequirements(true)">
                强行保存
              </button>
            </div>
          </div>
        </div>

        <div class="modal-footer" v-if="linkWarnings.length === 0">
          <button class="btn btn-secondary" @click="closeLinkReqModal">取消</button>
          <button class="btn btn-primary btn-glow" @click="persistLinkRequirements(false)">
            保存需求关联
          </button>
        </div>
      </div>
    </div>
  </div>
  <div class="loading-state-page" v-else>
    <div class="spinner"></div>
    <p>正在获取测试任务详情...</p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, reactive } from "vue";
import { useRoute, useRouter } from "vue-router";
import { testTasksApi, TestTask, TestTaskActivity } from "./api";
import { versionsApi, Version } from "../versions/api";
import { apiClient } from "../../shared/api/client";

interface Member {
  user_id: string;
  display_name: string;
  role_id?: string;
}

interface Requirement {
  id: string;
  requirement_no: string;
  requirementNo?: string;
  title: string;
  status: string;
}

const route = useRoute();
const router = useRouter();
const projectId = computed(() => route.params.projectId as string);
const taskId = computed(() => route.params.taskId as string);

// 核心状态
const task = ref<TestTask | null>(null);
const versions = ref<Version[]>([]);
const members = ref<Member[]>([]);
const allRequirements = ref<Requirement[]>([]);
const linkedRequirements = ref<Requirement[]>([]);
const activities = ref<TestTaskActivity[]>([]);

const currentTab = ref("activities");

// 只读状态保护
const isReadOnly = computed(() => {
  if (!task.value) return true;
  return ["COMPLETED", "ARCHIVED"].includes(task.value.status);
});

// 编辑表单
const updating = ref(false);
const newTag = ref("");
const editForm = reactive({
  title: "",
  priority: "MEDIUM" as "LOW" | "MEDIUM" | "HIGH" | "URGENT",
  ownerId: "",
  plannedStartAt: "",
  plannedEndAt: "",
  description: "",
  testGoal: "",
  excludedScope: "",
  tagsJson: [] as string[],
});

// 状态流转模态框表单
const transitionModalVisible = ref(false);
const transmitting = ref(false);
const pendingTargetStatus = ref("");
const transError = ref("");
const transForm = reactive({
  reasonCode: "REQUIREMENT_UNCLEAR",
  reasonText: "",
  reasonRequired: false,
});

// 格式化时间以匹配 datetime-local 控件
const parseToLocalDatetime = (isoStr: string) => {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// 加载详情与基础元数据
const fetchDetailData = async () => {
  try {
    const t = await testTasksApi.get(projectId.value, taskId.value);
    task.value = t;

    // 填充编辑表单
    editForm.title = t.title;
    editForm.priority = t.priority;
    editForm.ownerId = t.ownerId;
    editForm.plannedStartAt = parseToLocalDatetime(t.plannedStartAt);
    editForm.plannedEndAt = parseToLocalDatetime(t.plannedEndAt);
    editForm.description = t.description || "";
    editForm.testGoal = t.testGoal || "";
    editForm.excludedScope = t.excludedScope || "";
    editForm.tagsJson = t.tagsJson ? [...t.tagsJson] : [];

    // 获取页签属性
    fetchLinkedRequirements();
    fetchActivities();
  } catch (err: any) {
    alert(err.message || "拉取任务详情失败");
    router.push(`/projects/${projectId.value}/test-tasks`);
  }
};

// 获取项目基础选项
const fetchVersionsAndMembers = async () => {
  try {
    const [vList, mList] = await Promise.all([
      versionsApi.list(projectId.value, { limit: 100 }),
      apiClient.get(`/api/v1/projects/${projectId.value}/members`, (data) => data as Member[]),
    ]);
    versions.value = vList.items;
    members.value = mList;
  } catch (e) {
    console.error("加载详情备选项失败", e);
  }
};

// 标签增删
const addTag = () => {
  const t = newTag.value.trim();
  if (t && !editForm.tagsJson.includes(t)) {
    editForm.tagsJson.push(t);
  }
  newTag.value = "";
};

const removeTag = (tag: string) => {
  editForm.tagsJson = editForm.tagsJson.filter((x) => x !== tag);
};

// 更新基础信息
const updateTaskInfo = async () => {
  if (!task.value) return;
  updating.value = true;

  try {
    const start = new Date(editForm.plannedStartAt);
    const end = new Date(editForm.plannedEndAt);
    if (end <= start) {
      throw new Error("计划结束时间不能早于计划开始时间");
    }

    const payload = {
      title: editForm.title,
      priority: editForm.priority,
      ownerId: editForm.ownerId,
      plannedStartAt: start.toISOString(),
      plannedEndAt: end.toISOString(),
      description: editForm.description,
      testGoal: editForm.testGoal,
      excludedScope: editForm.excludedScope,
      tagsJson: editForm.tagsJson,
    };

    await testTasksApi.update(projectId.value, taskId.value, payload);
    alert("保存任务成功");
    fetchDetailData();
  } catch (err: any) {
    alert(err.message || "保存任务失败");
  } finally {
    updating.value = false;
  }
};

// 跳转到用例编写与脑图
function goToCaseWriting() {
  if (!task.value) return;
  router.push({
    path: `/projects/${projectId.value}/cases`,
    query: { sourceTaskId: task.value.id },
  });
}

function goToMindmap() {
  if (!task.value) return;
  router.push(`/projects/${projectId.value}/test-tasks/${task.value.id}/mindmap`);
}

function activeConsoleTab(tab: string) {
  currentTab.value = tab;
}

// 获取已关联需求列表
const fetchLinkedRequirements = async () => {
  try {
    const list = await apiClient.get(
      `/api/v1/projects/${projectId.value}/test-tasks/${taskId.value}/requirements`,
      (data) => data as Requirement[]
    );
    linkedRequirements.value = list;
  } catch (err) {
    console.error("加载关联需求列表失败", err);
  }
};

// 获取流转活动历史
const fetchActivities = async () => {
  try {
    const list = await testTasksApi.listActivities(projectId.value, taskId.value);
    activities.value = list;
  } catch (err) {
    console.error("加载流转活动失败", err);
  }
};

// 配置关联需求模态框
const linkReqModalVisible = ref(false);
const selectedReqId = ref<string | null>(null);
const linkWarnings = ref<any[]>([]);

const openLinkReqModal = async () => {
  try {
    // 1. 获取全量未归档需求
    const reqs = await apiClient.get(
      `/api/v1/projects/${projectId.value}/requirements`,
      (data) => data as Requirement[]
    );
    allRequirements.value = reqs.filter((r) => r.status !== "ARCHIVED");

    // 2. 初始化已勾选项 (单选)
    selectedReqId.value = linkedRequirements.value[0]?.id || null;
    linkWarnings.value = [];
    linkReqModalVisible.value = true;
  } catch (err: any) {
    alert("拉取项目需求选项失败: " + err.message);
  }
};

const closeLinkReqModal = () => {
  linkReqModalVisible.value = false;
  linkWarnings.value = [];
};

const clearLinkWarnings = () => {
  linkWarnings.value = [];
};

const persistLinkRequirements = async (force: boolean) => {
  try {
    const payload = {
      requirementId: selectedReqId.value,
      force: force,
    };

    const res = await apiClient.put(
      `/api/v1/projects/${projectId.value}/test-tasks/${taskId.value}/requirements`,
      payload
    );

    if (res.data && res.data.warnings && res.data.warnings.length > 0 && !force) {
      linkWarnings.value = res.data.warnings;
    } else {
      alert("关联需求成功！");
      closeLinkReqModal();
      fetchLinkedRequirements();
    }
  } catch (err: any) {
    alert("保存关联失败: " + (err.response?.data?.message || err.message));
  }
};

// 状态流转控制
const openTransitionModal = (targetStatus: string) => {
  pendingTargetStatus.value = targetStatus;
  transError.value = "";
  transForm.reasonText = "";

  if (targetStatus === "BLOCKED") {
    transForm.reasonCode = "REQUIREMENT_UNCLEAR";
    transForm.reasonRequired = true;
  } else {
    transForm.reasonRequired = false;
  }

  transitionModalVisible.value = false;
  executeTransitionDirectlyCheck();
};

const closeTransitionModal = () => {
  transitionModalVisible.value = false;
  transError.value = "";
};

const getTransitionModalTitle = () => {
  if (pendingTargetStatus.value === "COMPLETED") return "标记任务为已完成 (COMPLETED)";
  if (pendingTargetStatus.value === "BLOCKED") return "标记任务为阻塞状态 (BLOCKED)";
  if (pendingTargetStatus.value === "CANCELLED") return "取消此任务运行 (CANCELLED)";
  if (pendingTargetStatus.value === "UNBLOCK") return "解除任务阻塞状态";
  if (pendingTargetStatus.value === "RESTORE_CANCEL") return "恢复已取消任务为草稿";
  return "变更任务运行状态";
};

const executeTransitionDirectlyCheck = () => {
  const target = pendingTargetStatus.value;
  if (["READY", "IN_PROGRESS"].includes(target)) {
    executeTransitionDirectly(target);
  } else {
    transitionModalVisible.value = true;
  }
};

const executeTransitionDirectly = async (status: string) => {
  try {
    await testTasksApi.transition(projectId.value, taskId.value, {
      toStatus: status,
    });
    alert("状态变更成功！");
    fetchDetailData();
  } catch (err: any) {
    alert("状态流转失败: " + (err.response?.data?.message || err.message));
  }
};

const executeTransition = async () => {
  transmitting.value = true;
  transError.value = "";

  try {
    let target = pendingTargetStatus.value;
    let actualStatus = target;

    if (target === "UNBLOCK") {
      actualStatus = "IN_PROGRESS";
    } else if (target === "RESTORE_CANCEL") {
      actualStatus = "DRAFT";
    }

    const payload: any = {
      toStatus: actualStatus,
      reasonText: transForm.reasonText.trim(),
    };

    if (transForm.reasonRequired) {
      payload.reasonCode = transForm.reasonCode;
    }

    await testTasksApi.transition(projectId.value, taskId.value, payload);
    closeTransitionModal();
    fetchDetailData();
    alert("状态变更成功！");
  } catch (err: any) {
    transError.value = err.response?.data?.message || err.message || "流转失败";
  } finally {
    transmitting.value = false;
  }
};

const archiveTask = async () => {
  if (!confirm("归档后任务将无法在看板列表中直接展示。确定归档该任务吗？")) return;
  try {
    await testTasksApi.archive(projectId.value, taskId.value);
    alert("任务归档成功");
    fetchDetailData();
  } catch (err: any) {
    alert("归档失败: " + (err.response?.data?.message || err.message));
  }
};

const restoreArchived = async () => {
  try {
    await testTasksApi.restore(projectId.value, taskId.value);
    alert("任务已成功恢复为进行中状态！");
    fetchDetailData();
  } catch (err: any) {
    alert("激活恢复失败: " + (err.response?.data?.message || err.message));
  }
};

// 各种格式化工具
const formatStatus = (status: string) => {
  const map: Record<string, string> = {
    DRAFT: "草稿 (DRAFT)",
    READY: "待开始 (READY)",
    IN_PROGRESS: "进行中 (IN_PROGRESS)",
    BLOCKED: "已阻塞 (BLOCKED)",
    COMPLETED: "已完成 (COMPLETED)",
    CANCELLED: "已取消 (CANCELLED)",
    ARCHIVED: "已归档 (ARCHIVED)",
  };
  return map[status] || status;
};

const formatReqStatus = (status: string) => {
  const map: Record<string, string> = {
    DRAFT: "草稿",
    READY: "就绪",
    CANCELLED: "已取消",
    ARCHIVED: "已归档",
  };
  return map[status] || status;
};

const formatReasonCode = (code: string) => {
  const map: Record<string, string> = {
    REQUIREMENT_UNCLEAR: "需求不明确",
    ENVIRONMENT_ISSUE: "测试环境未就绪",
    CODE_NOT_READY: "开发代码未就绪",
    FORCE_ABORT: "项目强行终止",
    OTHER: "其他原因",
  };
  return map[code] || code;
};

const formatDatetime = (isoStr: string) => {
  if (!isoStr) return "";
  return new Date(isoStr).toLocaleString("zh-CN");
};

onMounted(() => {
  fetchVersionsAndMembers();
  fetchDetailData();
});
</script>

<style scoped>
.task-detail-page {
  padding: 20px;
  background: #0f172a;
  min-height: 100vh;
  color: #cbd5e1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 16px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.back-link {
  color: #94a3b8;
  text-decoration: none;
  font-weight: 500;
}

.back-link:hover {
  color: #38bdf8;
}

.task-no {
  color: #38bdf8;
  font-family: monospace;
  font-weight: 600;
}

.workflow-actions-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-badge {
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 600;
}

.status-badge.draft { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }
.status-badge.ready { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
.status-badge.in_progress { background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3); }
.status-badge.blocked { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.status-badge.completed { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.status-badge.cancelled { background: rgba(244, 63, 94, 0.15); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.3); }
.status-badge.archived { background: rgba(100, 116, 139, 0.15); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }

.detail-layout {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.card {
  background: rgba(30, 41, 59, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  backdrop-filter: blur(12px);
}

.info-card {
  flex: 3;
  padding: 24px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding-bottom: 12px;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
}

.read-only-badge {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}

/* 表单网络结构 */
.info-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
}

.form-group label.required::after {
  content: " *";
  color: #ef4444;
}

.form-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.form-control, .form-select {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: #f8fafc;
  font-size: 13.5px;
  padding: 8px 12px;
  height: 38px;
  transition: all 0.2s ease;
}

.form-control:focus, .form-select:focus {
  outline: none;
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.15);
}

.form-control.textarea {
  height: auto;
  resize: vertical;
}

.date-range-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
}

.range-sep {
  color: #64748b;
  font-size: 12px;
}

/* 标签样式 */
.tags-input-box {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 38px;
  padding: 4px 8px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
}

.tags-input-box.disabled {
  opacity: 0.6;
}

.form-tag {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #38bdf8;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tag-del {
  cursor: pointer;
  color: #38bdf8;
}

.tag-del:hover {
  color: #ef4444;
}

.tags-input-box input {
  background: transparent;
  border: none;
  outline: none;
  color: #f8fafc;
  font-size: 13px;
  padding: 4px 0;
  width: 80px;
}

/* 关联需求样式 */
.linked-requirement-display {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 38px;
  padding: 0 12px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
}

.req-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.req-badge {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.35);
  color: #818cf8;
  font-family: monospace;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.req-title {
  font-size: 13px;
  color: #e2e8f0;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-link-req {
  background: transparent;
  border: none;
  color: #38bdf8;
  font-size: 12px;
  cursor: pointer;

  &:hover {
    text-decoration: underline;
  }
}

.no-req {
  color: #64748b;
  font-size: 12.5px;
}

/* 右侧控制台面板 (25% 宽度) */
.action-console-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.console-card {
  padding: 20px;
}

.console-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.action-card {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;

  &:hover {
    background: rgba(56, 189, 248, 0.06);
    border-color: rgba(56, 189, 248, 0.3);
    transform: translateY(-2px);

    .go-arrow {
      color: #38bdf8;
      transform: translateX(4px);
    }
  }
}

.card-icon {
  font-size: 26px;
  width: 44px;
  height: 44px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-info {
  flex: 1;

  h4 {
    margin: 0 0 4px 0;
    font-size: 13.5px;
    color: #e2e8f0;
    font-weight: 600;
  }

  p {
    margin: 0;
    font-size: 11.5px;
    color: #64748b;
    line-height: 1.4;
  }
}

.go-arrow {
  font-size: 16px;
  color: #475569;
  transition: all 0.2s ease;
}

/* 辅助页签容器 */
.tab-container {
  background: rgba(30, 41, 59, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.tab-headers {
  display: flex;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 14px;
}

.tab-header-btn {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #64748b;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;

  &.active {
    color: #38bdf8;
    border-bottom-color: #38bdf8;
  }
}

.activities-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 220px;
  overflow-y: auto;
}

.timeline-node {
  border-left: 2px solid rgba(255, 255, 255, 0.06);
  padding-left: 12px;
  position: relative;
  font-size: 11.5px;

  &::before {
    content: "";
    position: absolute;
    left: -5px;
    top: 4px;
    width: 8px;
    height: 8px;
    background: #475569;
    border-radius: 50%;
  }
}

.node-time {
  color: #64748b;
  margin-bottom: 2px;
}

.node-title {
  color: #94a3b8;
}

.node-flow {
  color: #38bdf8;
}

.reason-text {
  margin: 4px 0 0 0;
  color: #cbd5e1;
  font-style: italic;
}

.ai-glow-card {
  padding: 12px;
  background: rgba(99, 102, 241, 0.05);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 8px;
  text-align: center;
}

.ai-glow-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 6px;

  h4 {
    margin: 0;
    font-size: 13px;
    color: #a5b4fc;
  }
}

.ai-desc {
  font-size: 11.5px;
  color: #94a3b8;
  line-height: 1.4;
  margin: 0 0 12px 0;
}

.ai-scanning-animation {
  position: relative;
  height: 48px;
  background: rgba(15, 23, 42, 0.4);
  border-radius: 4px;
  overflow: hidden;
}

.scanner-bar {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  background: #6366f1;
  box-shadow: 0 0 8px #6366f1;
  animation: scan 2s infinite linear;
}

.grid-mesh {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(99, 102, 241, 0.1) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(99, 102, 241, 0.1) 1px, transparent 1px);
  background-size: 10px 10px;
}

.metadata-section {
  display: flex;
  gap: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 12px;
  margin-bottom: 12px;
}

.meta-item {
  font-size: 12px;
  color: #64748b;
}

.meta-label {
  margin-right: 4px;
}

.meta-value {
  color: #94a3b8;
}

/* 按钮基础 */
.btn {
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  padding: 6px 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.btn-primary { background: #0284c7; color: #fff; }
.btn-primary:hover { background: #0369a1; }
.btn-indigo { background: #4f46e5; color: #fff; }
.btn-indigo:hover { background: #4338ca; }
.btn-emerald { background: #059669; color: #fff; }
.btn-emerald:hover { background: #047857; }
.btn-warning { background: #d97706; color: #fff; }
.btn-warning:hover { background: #b45309; }
.btn-secondary { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.1); color: #cbd5e1; }
.btn-secondary:hover { background: rgba(255, 255, 255, 0.12); }
.btn-sm { font-size: 11.5px; padding: 4px 10px; }

.btn-glow {
  box-shadow: 0 0 12px rgba(2, 132, 199, 0.35);
}

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  width: 440px;
  color: #cbd5e1;
}

.link-req-modal {
  width: 500px;
}

.modal-header {
  height: 52px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.modal-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #f1f5f9;
}

.btn-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 24px;
  cursor: pointer;
}

.modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal-footer {
  padding: 14px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.desc-info {
  font-size: 12.5px;
  color: #94a3b8;
}

.req-checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
}

.checkbox-label-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  cursor: pointer;

  &.selected {
    background: rgba(56, 189, 248, 0.08);
    border-color: rgba(56, 189, 248, 0.3);
  }
}

.card-req-no {
  font-family: monospace;
  font-weight: 600;
  color: #38bdf8;
}

.card-req-title {
  font-size: 13px;
  color: #cbd5e1;
}

.warning-ul {
  margin: 6px 0 0 0;
  padding-left: 16px;
  color: #f87171;
  font-size: 12px;
}

.warning-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

.btn-red { background: #dc2626; color: #fff; }
.btn-red:hover { background: #b91c1c; }
.class-red { background: #ef4444; color: #fff; }

.info-alert {
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
}

.danger-alert {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.error-msg {
  color: #f87171;
  font-size: 12px;
}

.loading-state-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 380px;
  color: #64748b;
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(56, 189, 248, 0.1);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes scan {
  0%, 100% { top: 0; }
  50% { top: 46px; }
}

@media (max-width: 1024px) {
  .detail-layout {
    flex-direction: column;
  }

  .info-card {
    width: 100%;
  }

  .action-console-panel {
    width: 100%;
  }
}
</style>
