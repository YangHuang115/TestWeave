<template>
  <div class="requirement-detail-wrapper" v-if="requirement">
    <!-- 面包屑 -->
    <div class="breadcrumb">
      <router-link :to="`/projects/${projectId}/versions/${versionId}`" class="back-link">
        📂 返回版本详情
      </router-link>
      <span class="sep">/</span>
      <span class="curr">{{ requirement.requirement_no }}</span>
    </div>

    <!-- 需求顶栏与操作 (查看/编辑/删除操作放在这里) -->
    <div class="req-hero">
      <div class="hero-left">
        <div class="title-row">
          <span class="req-no">{{ requirement.requirement_no }}</span>
          <h2>{{ requirement.title }}</h2>
        </div>
        <div class="meta-row">
          <span class="meta-item">
            <span class="label">状态:</span>
            <span class="val">{{ formatStatus(requirement.status) }}</span>
          </span>
          <span class="meta-item">
            <span class="label">优先级:</span>
            <span class="val">{{ formatPriority(requirement.priority) }}</span>
          </span>
          <span class="meta-item">
            <span class="label">负责人:</span>
            <span class="val">{{ ownerName }}</span>
          </span>
        </div>
      </div>
      <div class="hero-right">
        <!-- 需求操作组 (修改、归档、删除操作移到了详情页) -->
        <div class="actions-group" v-if="projectStore.hasPermission('version.manage')">
          <button class="action-btn edit" @click="openEditModal">编辑需求</button>
          <button class="action-btn archive" @click="void handleArchive()">
            {{ requirement.status === "ARCHIVED" ? "恢复需求" : "归档需求" }}
          </button>
          <button class="action-btn delete" @click="void confirmDelete()">移出版本</button>
        </div>
      </div>
    </div>

    <!-- Tab 切换 -->
    <div class="tabs-nav">
      <button
        v-for="t in tabs"
        :key="t.id"
        :class="['tab-btn', { active: activeTab === t.id }]"
        @click="activeTab = t.id"
      >
        {{ t.name }}
      </button>
    </div>

    <!-- Tab 内容 -->
    <div class="tab-content">
      <!-- 概览页签 -->
      <div v-if="activeTab === 'overview'" class="overview-tab">
        <div class="info-card">
          <h4>需求描述</h4>
          <p class="desc-text">{{ requirement.description || "无详细描述说明。" }}</p>
        </div>
        <div class="info-card">
          <h4>验收标准</h4>
          <p class="desc-text">{{ requirement.acceptance_criteria || "无明确验收标准。" }}</p>
        </div>
      </div>

      <!-- 附件页签 (M02 阶段 4 真实对接) -->
      <div v-else-if="activeTab === 'attachments'" class="attachments-tab">
        <!-- 上传卡片 -->
        <div class="attachment-upload-card" v-if="projectStore.hasPermission('version.manage')">
          <div class="upload-trigger">
            <span class="upload-icon">📤</span>
            <div class="upload-prompt">
              <span class="highlight">点击上传</span> 或拖拽 Word 附件
            </div>
            <div class="upload-tip">支持 .docx 格式，大小不超过 20MB</div>
            <input
              type="file"
              accept=".docx"
              :disabled="isUploading"
              @change="void handleFileUpload($event)"
              class="file-input"
            />
          </div>
          <div v-if="isUploading" class="uploading-banner">文件上传安全审计与沙箱扫描中...</div>
          <div v-if="uploadError" class="upload-error-banner">⚠️ {{ uploadError }}</div>
        </div>

        <!-- 附件列表 -->
        <div class="attachments-list-card">
          <div class="list-header">
            <h4>已上传附件 ({{ attachments.length }})</h4>
          </div>
          <div v-if="attachments.length === 0" class="empty-attachments">
            <span class="empty-icon">📎</span>
            <p>暂无关联的 Word 附件，支持上传需求规格说明书以配合后续用例生成。</p>
          </div>
          <table v-else class="attachments-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>大小</th>
                <th>SHA-256</th>
                <th>上传人</th>
                <th>上传时间</th>
                <th class="actions-th">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="att in attachments" :key="att.id">
                <td class="filename-td">📄 {{ att.original_filename }}</td>
                <td>{{ formatFileSize(att.size_bytes) }}</td>
                <td class="sha-td">{{ att.sha256.substring(0, 8) }}</td>
                <td>{{ formatUploader(att.uploaded_by) }}</td>
                <td>{{ formatDate(att.uploaded_at) }}</td>
                <td class="actions-td">
                  <button class="att-action-btn download" @click="void handleDownload(att)">
                    下载
                  </button>
                  <button
                    v-if="projectStore.hasPermission('version.manage')"
                    class="att-action-btn delete"
                    @click="void handleDeleteAttachment(att)"
                  >
                    删除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Diff 页签 (M02 阶段 7/8 真实对接) -->
      <div v-else-if="activeTab === 'diff'" class="diff-tab-layout">
        <!-- 左侧: 关联提交列表 -->
        <div class="commits-list-panel">
          <div class="panel-header">
            <h4>关联提交列表 ({{ commits.length }})</h4>
          </div>
          <div v-if="commits.length === 0" class="empty-list-prompt">
            <span class="prompt-icon">💻</span>
            <p>
              暂无关联的 Git 提交。系统将在后台同步时，根据 Commit Message 精确匹配并建立绑定关联。
            </p>
          </div>
          <div v-else class="commits-scroll-box">
            <div
              v-for="c in commits"
              :key="c.sha"
              class="commit-item"
              :class="{ active: selectedCommit?.id === c.id }"
              @click="void selectCommit(c)"
            >
              <div class="commit-header">
                <span class="commit-sha">{{ c.sha.substring(0, 8) }}</span>
                <span class="commit-author">{{ c.author_name }}</span>
              </div>
              <p class="commit-msg">{{ c.message }}</p>
              <span class="commit-time">{{ formatDate(c.committed_at) }}</span>
            </div>
          </div>
        </div>

        <!-- 右侧: 变动文件与 Diff 详情 -->
        <div class="diff-viewer-panel">
          <div v-if="!selectedCommit" class="viewer-placeholder">
            <span>👈 请在左侧选择一个 Git 提交记录以查看变动文件及差异。</span>
          </div>
          <div v-else class="viewer-body">
            <!-- 提交详情汇总 -->
            <div class="selected-commit-summary">
              <h5>{{ selectedCommit.message }}</h5>
              <div class="commit-meta-details">
                <span
                  >提交哈希: <code class="sha">{{ selectedCommit.sha }}</code></span
                >
                <span>作者: {{ selectedCommit.author_name }}</span>
                <span>变动文件: {{ selectedCommit.files_changed }} 个</span>
                <span class="stats-badge">
                  <span class="add">+{{ selectedCommit.additions }}</span>
                  <span class="del">-{{ selectedCommit.deletions }}</span>
                </span>
              </div>
            </div>

            <!-- 文件列表与 diff 分离 -->
            <div class="diff-split-container">
              <!-- 文件树/树列表 -->
              <div class="files-sidebar">
                <div class="files-sidebar-header">变动文件列表</div>
                <div v-if="files.length === 0" class="empty-files">无文件变更记录</div>
                <div v-else class="files-list">
                  <div
                    v-for="f in files"
                    :key="f.id"
                    class="file-item"
                    :class="{ active: selectedFile?.id === f.id }"
                    @click="void selectFile(f)"
                  >
                    <span :class="['change-type-icon', f.change_type.toLowerCase()]">
                      {{ f.change_type.substring(0, 1) }}
                    </span>
                    <span class="file-name" :title="f.new_path">
                      {{ getFilename(f.new_path) }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- Diff 代码查看器 -->
              <div class="code-diff-area">
                <div v-if="!selectedFile" class="diff-placeholder">
                  请选择左侧的文件以浏览 Diff patch 差异。
                </div>
                <div v-else-if="loadingPatch" class="diff-placeholder">⏳ 正在拉取代码变动...</div>
                <div v-else class="diff-container">
                  <div class="diff-file-header">
                    📄 {{ selectedFile.new_path }}
                    <span class="truncated-tip" v-if="patchTruncated">
                      ⚠️ 提示: 由于该文件补丁过大，已被系统自动截断显示。
                    </span>
                  </div>
                  <pre class="diff-pre" v-html="renderedPatchHtml"></pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 关联对象 -->
      <div v-else-if="activeTab === 'relations'" class="relations-tab">
        <div class="pane-inner">
          <div class="section-header">
            <h4>关联测试任务 (M03)</h4>
            <router-link :to="`/projects/${projectId}/test-tasks`" class="btn-link-out">
              去任务管理关联需求
            </router-link>
          </div>

          <div v-if="relatedTasksLoading" class="loading-inline">
            <div class="spinner-sm"></div>
            <span>正在加载关联任务...</span>
          </div>

          <div v-else-if="relatedTasks.length > 0" class="related-tasks-list">
            <div v-for="t in relatedTasks" :key="t.id" class="related-task-card">
              <div class="card-top">
                <span class="task-no-lbl">{{ t.taskNo }}</span>
                <span class="task-type-lbl" :class="t.taskType">
                  {{ t.taskType === 'CASE_DESIGN' ? '设计' : '执行' }}
                </span>
                <span class="task-status-lbl" :class="t.status.toLowerCase()">
                  {{ formatStatusText(t.status) }}
                </span>
              </div>
              <router-link :to="`/projects/${projectId}/test-tasks/${t.id}`" class="task-title-link">
                {{ t.title }}
              </router-link>
              <div class="card-bottom">
                <span class="lbl-owner">负责人: {{ t.ownerName || '未指定' }}</span>
                <span class="lbl-date">截止: {{ formatDateShort(t.plannedEndAt) }}</span>
              </div>
            </div>
          </div>

          <div class="empty-placeholder" v-else>
            <span class="icon-empty">📁</span>
            <p>该需求当前未被任何测试任务关联覆盖。</p>
          </div>
        </div>
      </div>

      <!-- 变更记录 -->
      <div v-else-if="activeTab === 'audit'" class="audit-tab">
        <div class="placeholder-card">
          <span class="icon">📜</span>
          <h4>变更审计轨迹</h4>
          <p>此需求的生命周期变动、负责人调整和附件上传将被记录于审计事件表中。</p>
        </div>
      </div>
    </div>

    <!-- 编辑需求弹窗 Modal (操作包含在此详情页内) -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal-card">
        <h3>编辑需求</h3>
        <p class="subtitle">更新当前需求基本元数据与描述。</p>
        <form @submit.prevent="void handleUpdateRequirement()">
          <div class="form-group">
            <label for="req-no">需求单号 *</label>
            <input
              id="req-no"
              v-model="editForm.requirement_no"
              type="text"
              required
              :disabled="isSaving"
            />
          </div>

          <div class="form-group">
            <label for="req-title">需求标题 *</label>
            <input
              id="req-title"
              v-model="editForm.title"
              type="text"
              required
              :disabled="isSaving"
            />
          </div>

          <div class="form-group">
            <label for="req-priority">优先级 *</label>
            <select id="req-priority" v-model="editForm.priority" required :disabled="isSaving">
              <option value="HIGH">高</option>
              <option value="MEDIUM">中</option>
              <option value="LOW">低</option>
            </select>
          </div>

          <div class="form-group">
            <label for="req-owner">负责人</label>
            <select id="req-owner" v-model="editForm.owner_id" :disabled="isSaving">
              <option value="">未分配</option>
              <option v-for="m in members" :key="m.user_id" :value="m.user_id">
                {{ m.display_name }} ({{ m.username }})
              </option>
            </select>
          </div>

          <div class="form-group">
            <label for="req-status">需求状态 *</label>
            <select id="req-status" v-model="editForm.status" required :disabled="isSaving">
              <option value="DRAFT">草稿</option>
              <option value="READY">就绪</option>
              <option value="CANCELLED">已取消</option>
              <option value="ARCHIVED">已归档</option>
            </select>
          </div>

          <div class="form-group">
            <label for="req-desc">需求描述</label>
            <textarea id="req-desc" v-model="editForm.description" :disabled="isSaving"></textarea>
          </div>

          <div v-if="saveError" class="error-banner">⚠️ {{ saveError }}</div>

          <div class="modal-actions">
            <button
              type="button"
              class="cancel-btn"
              :disabled="isSaving"
              @click="showEditModal = false"
            >
              取消
            </button>
            <button type="submit" class="submit-btn" :disabled="isSaving">
              {{ isSaving ? "保存中..." : "保存修改" }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useProjectStore } from "../../shared/stores/project";
import { apiClient } from "../../shared/api/client";
import { testTasksApi, TestTask } from "../tasks/api";

interface Member {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
}

interface RequirementDetail {
  id: string;
  requirement_no: string;
  title: string;
  description?: string;
  acceptance_criteria?: string;
  priority: string;
  status: string;
  owner_id: string;
  rowVersion: number;
}

interface TabItem {
  id: string;
  name: string;
}

const route = useRoute();
const router = useRouter();
const projectStore = useProjectStore();
const projectId = route.params.projectId as string;
const versionId = route.params.versionId as string;
const requirementId = route.params.requirementId as string;

// 数据
const requirement = ref<RequirementDetail | null>(null);
const members = ref<Member[]>([]);
const activeTab = ref("overview");

const tabs: TabItem[] = [
  { id: "overview", name: "概览" },
  { id: "attachments", name: "附件" },
  { id: "diff", name: "Diff" },
  { id: "relations", name: "关联对象" },
  { id: "audit", name: "变更记录" },
];

const ownerName = computed(() => {
  if (!requirement.value) return "";
  const m = members.value.find((x) => x.user_id === requirement.value?.owner_id);
  return m ? m.display_name : "未分配";
});

// 加载数据
async function loadData() {
  try {
    const data = await apiClient.get(
      `/api/v1/projects/${projectId}/members`,
      (val) => val as Member[],
    );
    members.value = data;

    // 试图从后端加载真实需求 (等阶段 3 后端写完后生效)
    try {
      const req = await apiClient.get(
        `/api/v1/projects/${projectId}/requirements/${requirementId}`,
        (val) => val as RequirementDetail,
      );
      requirement.value = req;
    } catch {
      // 降级使用 Mock 数据以跑通 UI
      console.warn("未检测到后端需求详情 API，采用 Mock 渲染");
      requirement.value = {
        id: requirementId,
        requirement_no: "REQ-1001",
        title: "支持支付宝沙箱回调安全校验",
        description:
          "本需求旨在升级支付宝沙箱回调，加强签名验证及防重放机制。\n1. 支持签名 MD5/RSA 双重校验；\n2. 引入 Token Nonce 做重放防御。",
        acceptance_criteria: "1. 签名失败返回 403 阻断；\n2. 重复 Nonce 请求识别并告警。",
        priority: "HIGH",
        status: "READY",
        owner_id: members.value[0]?.user_id || "",
        rowVersion: 1,
      };
    }
  } catch (e: unknown) {
    const err = e as { message?: string };
    console.error("加载需求详情失败", err.message);
  }
}

// 格式化函数
function formatStatus(status: string) {
  const mapping: Record<string, string> = {
    DRAFT: "草稿",
    READY: "待测试分析",
    CANCELLED: "已取消",
    ARCHIVED: "已归档",
  };
  return mapping[status] || status;
}

function formatPriority(priority: string) {
  const mapping: Record<string, string> = {
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低",
  };
  return mapping[priority] || priority;
}

// 按钮操作逻辑 (编辑/归档/移出版本)
const showEditModal = ref(false);
const isSaving = ref(false);
const saveError = ref<string | null>(null);
const editForm = reactive({
  requirement_no: "",
  title: "",
  priority: "MEDIUM",
  owner_id: "",
  description: "",
  status: "DRAFT",
});

function openEditModal() {
  if (!requirement.value) return;
  saveError.value = null;
  editForm.requirement_no = requirement.value.requirement_no;
  editForm.title = requirement.value.title;
  editForm.priority = requirement.value.priority;
  editForm.owner_id = requirement.value.owner_id || "";
  editForm.description = requirement.value.description || "";
  editForm.status = requirement.value.status;
  showEditModal.value = true;
}

async function handleUpdateRequirement() {
  if (!requirement.value) return;
  isSaving.value = true;
  saveError.value = null;

  try {
    const payload = {
      requirement_no: editForm.requirement_no,
      title: editForm.title,
      priority: editForm.priority,
      owner_id: editForm.owner_id || undefined,
      description: editForm.description,
      status: editForm.status,
      rowVersion: requirement.value.rowVersion,
      force_change_no: false,
    };
    const updated = await apiClient.patch(
      `/api/v1/projects/${projectId}/requirements/${requirementId}`,
      (data) => data as RequirementDetail,
      payload,
    );
    requirement.value = updated;
    showEditModal.value = false;
  } catch (e: unknown) {
    const err = e as Record<string, unknown>;
    const code = typeof err.code === "string" ? err.code : undefined;
    const status = typeof err.status === "number" ? err.status : undefined;
    const message = typeof err.message === "string" ? err.message : "";

    if (code === "REQUIREMENT_HAS_COMMITS") {
      if (
        confirm("该需求已有关联的代码提交。修改单号将导致旧代码 Diff 关联失效。确认要强制修改吗？")
      ) {
        try {
          const updated = await apiClient.patch(
            `/api/v1/projects/${projectId}/requirements/${requirementId}`,
            (data) => data as RequirementDetail,
            {
              requirement_no: editForm.requirement_no,
              title: editForm.title,
              priority: editForm.priority,
              owner_id: editForm.owner_id || undefined,
              description: editForm.description,
              status: editForm.status,
              rowVersion: requirement.value.rowVersion,
              force_change_no: true,
            },
          );
          requirement.value = updated;
          showEditModal.value = false;
        } catch (innerE: unknown) {
          const innerErr = innerE as Record<string, unknown>;
          saveError.value =
            typeof innerErr.message === "string" ? innerErr.message : "强制更新失败";
        }
      }
    } else if (status === 404 && requirement.value) {
      // 降级 mock 模拟
      requirement.value.requirement_no = editForm.requirement_no;
      requirement.value.title = editForm.title;
      requirement.value.priority = editForm.priority;
      requirement.value.owner_id = editForm.owner_id;
      requirement.value.description = editForm.description;
      requirement.value.status = editForm.status;
      showEditModal.value = false;
    } else {
      saveError.value = message || "更新需求失败";
    }
  } finally {
    isSaving.value = false;
  }
}

async function handleArchive() {
  if (!requirement.value) return;
  const isCurrentlyArchived = requirement.value.status === "ARCHIVED";
  const newStatus = isCurrentlyArchived ? "READY" : "ARCHIVED";
  try {
    await apiClient.post(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/${isCurrentlyArchived ? "restore" : "archive"}`,
      (data) => data,
    );
    requirement.value.status = newStatus;
  } catch (e: unknown) {
    const err = e as { status?: number };
    if (err.status === 404 && requirement.value) {
      requirement.value.status = newStatus;
    } else {
      alert("操作失败");
    }
  }
}

async function confirmDelete() {
  if (confirm("确认要将此需求从该版本中解除关联吗？(不会物理删除该需求本身)")) {
    try {
      await apiClient.delete(
        `/api/v1/projects/${projectId}/versions/${versionId}/requirements/${requirementId}`,
        (data) => data,
      );
      void router.push(`/projects/${projectId}/versions/${versionId}`);
    } catch (e: unknown) {
      const err = e as { status?: number };
      if (err.status === 404) {
        void router.push(`/projects/${projectId}/versions/${versionId}`);
      } else {
        alert("移出版本失败");
      }
    }
  }
}

interface RequirementAttachment {
  id: string;
  requirement_id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by: string | null;
  uploaded_at: string;
}

const attachments = ref<RequirementAttachment[]>([]);
const isUploading = ref(false);
const uploadError = ref<string | null>(null);

async function loadAttachments() {
  try {
    const list = await apiClient.get(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/attachments`,
      (val) => val as RequirementAttachment[],
    );
    attachments.value = list;
  } catch (e: unknown) {
    console.error("加载附件列表失败", e);
  }
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  if (!target.files || target.files.length === 0) return;
  const file = target.files[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".docx")) {
    uploadError.value = "仅支持上传 Word (.docx) 格式的文档";
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    uploadError.value = "文件大小不得超过 20MB";
    return;
  }

  isUploading.value = true;
  uploadError.value = null;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await apiClient.post(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/attachments`,
      (val) => val as RequirementAttachment,
      formData,
    );
    attachments.value.unshift(res);
    target.value = "";
  } catch (e: unknown) {
    const err = e as { message?: string };
    uploadError.value = err.message || "文件上传失败，可能包含不安全宏脚本或已损坏";
  } finally {
    isUploading.value = false;
  }
}

async function handleDownload(att: RequirementAttachment) {
  try {
    const response = await fetch(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/attachments/${att.id}`,
      {
        headers: {
          "X-CSRF-Token": document.cookie.match(/xsrf_token=([^;]+)/)?.[1] || "",
        },
      },
    );
    if (!response.ok) {
      throw new Error("下载附件失败");
    }
    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = att.original_filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(downloadUrl);
  } catch {
    alert("下载文件失败或无权限");
  }
}

async function handleDeleteAttachment(att: RequirementAttachment) {
  if (!confirm(`确认要删除附件 "${att.original_filename}" 吗？`)) return;

  try {
    await apiClient.delete(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/attachments/${att.id}`,
      (val) => val,
    );
    attachments.value = attachments.value.filter((x) => x.id !== att.id);
  } catch (e: unknown) {
    const err = e as { message?: string };
    alert(err.message || "删除附件失败");
  }
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatUploader(userId: string | null): string {
  if (!userId) return "未知";
  const m = members.value.find((x) => x.user_id === userId);
  return m ? m.display_name : "项目成员";
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

interface CommitDetail {
  id: string;
  sha: string;
  author_name: string;
  committer_name: string;
  committed_at: string;
  message: string;
  files_changed: number;
  additions: number;
  deletions: number;
}

interface CommitFileDetail {
  id: string;
  old_path: string | null;
  new_path: string;
  change_type: string;
  is_binary: boolean;
  additions: number;
  deletions: number;
  patch_size_bytes: number;
  patch_truncated: boolean;
}

const commits = ref<CommitDetail[]>([]);
const selectedCommit = ref<CommitDetail | null>(null);

const files = ref<CommitFileDetail[]>([]);
const selectedFile = ref<CommitFileDetail | null>(null);

const loadingPatch = ref(false);
const patchContent = ref("");
const patchTruncated = ref(false);

async function loadCommits() {
  try {
    const list = await apiClient.get(
      `/api/v1/projects/${projectId}/requirements/${requirementId}/commits`,
      (val) => val as CommitDetail[],
    );
    commits.value = list;
    if (list.length > 0 && list[0]) {
      void selectCommit(list[0]);
    } else {
      selectedCommit.value = null;
      files.value = [];
      selectedFile.value = null;
    }
  } catch (e) {
    console.error("加载关联提交失败", e);
  }
}

async function selectCommit(c: CommitDetail) {
  selectedCommit.value = c;
  files.value = [];
  selectedFile.value = null;
  patchContent.value = "";

  try {
    const fileList = await apiClient.get(
      `/api/v1/projects/${projectId}/commits/${c.id}/files`,
      (val) => val as CommitFileDetail[],
    );
    files.value = fileList;
    if (fileList.length > 0 && fileList[0]) {
      void selectFile(fileList[0]);
    }
  } catch (e) {
    console.error("加载变更文件失败", e);
  }
}

async function selectFile(f: CommitFileDetail) {
  selectedFile.value = f;
  patchContent.value = "";
  patchTruncated.value = false;

  if (f.is_binary) {
    patchContent.value = "无法渲染二进制文件的代码差异差异。";
    return;
  }

  loadingPatch.value = true;
  try {
    const res = await apiClient.get(
      `/api/v1/projects/${projectId}/commits/${selectedCommit.value?.id}/files/${f.id}/patch`,
      (val) => val as { patch: string; truncated: boolean },
    );
    patchContent.value = res.patch;
    patchTruncated.value = res.truncated;
  } catch {
    patchContent.value = "加载差异 Diff 失败，可能文件已被擦除。";
  } finally {
    loadingPatch.value = false;
  }
}

const renderedPatchHtml = computed(() => {
  const raw = patchContent.value;
  if (!raw) return '<div class="empty-diff">无差异 Patch 内容。</div>';
  const lines = raw.split("\n");
  return lines
    .map((line) => {
      let cls = "normal";
      if (line.startsWith("+")) {
        cls = "addition";
      } else if (line.startsWith("-")) {
        cls = "deletion";
      } else if (line.startsWith("@@")) {
        cls = "chunk";
      }
      const safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<div class="diff-line ${cls}">${safeLine}</div>`;
    })
    .join("");
});

function getFilename(pathStr: string): string {
  if (!pathStr) return "";
  const idx = pathStr.lastIndexOf("/");
  return idx === -1 ? pathStr : pathStr.substring(idx + 1);
}

const relatedTasks = ref<TestTask[]>([]);
const relatedTasksLoading = ref(false);

const loadRelatedTasks = async () => {
  relatedTasksLoading.value = true;
  try {
    const res = await testTasksApi.list(projectId, { requirementId: requirementId });
    relatedTasks.value = res.items;
  } catch (e) {
    console.error("加载关联测试任务失败", e);
  } finally {
    relatedTasksLoading.value = false;
  }
};

const formatStatusText = (s: string) => {
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

const formatDateShort = (dtStr: string) => {
  if (!dtStr) return "-";
  const d = new Date(dtStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
};

watch(activeTab, (newTab) => {
  if (newTab === "attachments") {
    void loadAttachments();
  } else if (newTab === "diff") {
    void loadCommits();
  } else if (newTab === "relations") {
    void loadRelatedTasks();
  }
});

onMounted(() => {
  void loadData();
  if (activeTab.value === "attachments") {
    void loadAttachments();
  } else if (activeTab.value === "diff") {
    void loadCommits();
  } else if (activeTab.value === "relations") {
    void loadRelatedTasks();
  }
});
</script>

<style scoped>
.requirement-detail-wrapper {
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
  font-family: monospace;
}

.req-hero {
  background: rgba(30, 41, 59, 0.3);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
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

.req-no {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12.5px;
  font-weight: 600;
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

.actions-group {
  display: flex;
  gap: 12px;
}

.action-btn {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: #cbd5e1;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}

.action-btn.edit {
  color: #60a5fa;
  border-color: rgba(96, 165, 250, 0.3);
}

.action-btn.delete {
  color: #f87171;
  border-color: rgba(248, 113, 113, 0.3);
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
}

.tab-btn:hover {
  color: #f1f5f9;
}

.tab-btn.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
}

.tab-content {
  min-height: 240px;
}

/* Info Cards */
.info-card {
  background: rgba(30, 41, 59, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}

.info-card h4 {
  margin: 0 0 12px;
  font-size: 14.5px;
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

/* Placeholder Cards for Unintegrated modules */
.placeholder-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 240px;
  border: 1px dashed rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  text-align: center;
  padding: 40px;
}

.placeholder-card .icon {
  font-size: 32px;
  margin-bottom: 12px;
}

.placeholder-card h4 {
  margin: 0 0 8px;
  font-size: 15px;
}

.placeholder-card p {
  color: #64748b;
  font-size: 13px;
  max-width: 440px;
  margin: 0;
  line-height: 1.6;
}

/* Form Modals */
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
  height: 100px;
  resize: vertical;
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

/* Attachments Tab Styles */
.attachment-upload-card {
  background: rgba(30, 41, 59, 0.2);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 30px;
  text-align: center;
  margin-bottom: 24px;
  transition: all 0.3s;
}

.attachment-upload-card:hover {
  background: rgba(30, 41, 59, 0.3);
  border-color: #6366f1;
}

.upload-trigger {
  position: relative;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.file-input {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.upload-icon {
  font-size: 28px;
}

.upload-prompt {
  font-size: 14px;
  color: #cbd5e1;
}

.upload-prompt .highlight {
  color: #6366f1;
  font-weight: 500;
}

.upload-tip {
  font-size: 12px;
  color: #64748b;
}

.uploading-banner {
  margin-top: 12px;
  font-size: 13px;
  color: #38bdf8;
  animation: pulse 2s infinite;
}

.upload-error-banner {
  margin-top: 12px;
  font-size: 13px;
  color: #f87171;
}

.attachments-list-card {
  background: rgba(30, 41, 59, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 24px;
}

.attachments-list-card h4 {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 600;
}

.empty-attachments {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 30px;
  text-align: center;
  color: #64748b;
}

.empty-attachments .empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.empty-attachments p {
  font-size: 13px;
  margin: 0;
}

.attachments-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.attachments-table th,
.attachments-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.attachments-table th {
  color: #64748b;
  font-weight: 500;
}

.filename-td {
  color: #f1f5f9;
  font-weight: 500;
}

.sha-td {
  font-family: monospace;
  color: #94a3b8;
}

.actions-th,
.actions-td {
  text-align: right;
}

.att-action-btn {
  background: transparent;
  border: none;
  font-size: 13px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  margin-left: 6px;
  transition: all 0.2s;
}

.att-action-btn.download {
  color: #60a5fa;
}

.att-action-btn.download:hover {
  background: rgba(96, 165, 250, 0.1);
}

.att-action-btn.delete {
  color: #f87171;
}

.att-action-btn.delete:hover {
  background: rgba(248, 113, 113, 0.1);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

/* Diff Tab Split Layout */
.diff-tab-layout {
  display: flex;
  gap: 20px;
  min-height: 480px;
}

.commits-list-panel {
  width: 280px;
  background: rgba(30, 41, 59, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.commits-list-panel .panel-header {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.commits-list-panel h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.empty-list-prompt {
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}

.empty-list-prompt .prompt-icon {
  font-size: 28px;
  margin-bottom: 8px;
  display: block;
}

.empty-list-prompt p {
  font-size: 12.5px;
  margin: 0;
  line-height: 1.6;
}

.commits-scroll-box {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 520px;
}

.commit-item {
  background: rgba(15, 23, 42, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.commit-item:hover {
  background: rgba(15, 23, 42, 0.4);
  border-color: rgba(255, 255, 255, 0.08);
}

.commit-item.active {
  background: rgba(99, 102, 241, 0.12);
  border-color: #6366f1;
}

.commit-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.commit-sha {
  font-family: monospace;
  font-size: 12px;
  color: #a5b4fc;
  font-weight: 600;
}

.commit-author {
  font-size: 11.5px;
  color: #94a3b8;
}

.commit-msg {
  font-size: 12.5px;
  color: #cbd5e1;
  margin: 0 0 6px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.commit-time {
  font-size: 11px;
  color: #64748b;
}

/* Right Diff Viewer Panel */
.diff-viewer-panel {
  flex: 1;
  background: rgba(30, 41, 59, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.viewer-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
  font-size: 14px;
  padding: 40px;
}

.viewer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.selected-commit-summary {
  background: rgba(15, 23, 42, 0.3);
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.selected-commit-summary h5 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: #f1f5f9;
}

.commit-meta-details {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: #94a3b8;
  align-items: center;
}

.commit-meta-details code.sha {
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  color: #a5b4fc;
}

.stats-badge {
  display: flex;
  gap: 8px;
  font-family: monospace;
  font-weight: bold;
}

.stats-badge .add {
  color: #34d399;
}

.stats-badge .del {
  color: #f87171;
}

/* Split container inside viewer */
.diff-split-container {
  display: flex;
  flex: 1;
  min-height: 420px;
  max-height: 460px;
}

.files-sidebar {
  width: 200px;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(15, 23, 42, 0.1);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.files-sidebar-header {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.files-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.file-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.file-item.active {
  background: rgba(99, 102, 241, 0.08);
}

.file-item .change-type-icon {
  font-size: 10px;
  font-weight: bold;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  color: #ffffff;
}

.file-item .change-type-icon.add {
  background: #059669;
}

.file-item .change-type-icon.modify {
  background: #d97706;
}

.file-item .change-type-icon.delete {
  background: #dc2626;
}

.file-item .change-type-icon.rename {
  background: #2563eb;
}

.file-item .file-name {
  font-size: 13px;
  color: #cbd5e1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-item.active .file-name {
  color: #a5b4fc;
  font-weight: 500;
}

/* Code Diff Area */
.code-diff-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #0f172a;
  overflow: hidden;
}

.diff-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #475569;
  font-size: 13.5px;
  padding: 20px;
}

.diff-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.diff-file-header {
  padding: 10px 16px;
  background: #1e293b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 13px;
  color: #94a3b8;
  font-family: monospace;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.truncated-tip {
  color: #f59e0b;
  font-size: 12px;
}

.diff-pre {
  margin: 0;
  padding: 12px;
  overflow: auto;
  flex: 1;
  font-family: monospace;
  font-size: 12px;
  line-height: 1.6;
  background: #0f172a;
  color: #e2e8f0;
}

/* Diff Lines Colors */
:deep(.diff-line) {
  padding: 1px 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

:deep(.diff-line.addition) {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
}

:deep(.diff-line.deletion) {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

:deep(.diff-line.chunk) {
  background: rgba(99, 102, 241, 0.1);
  color: #818cf8;
  font-weight: 500;
  border-bottom: 1px dashed rgba(99, 102, 241, 0.15);
  margin: 4px 0;
}

/* M03 关联任务页签样式 */
.pane-inner {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 8px;
}
.section-header h4 {
  margin: 0;
  font-size: 15px;
  color: #cbd5e1;
}
.btn-link-out {
  color: #818cf8;
  font-size: 13px;
  text-decoration: none;
  font-weight: 500;
}
.btn-link-out:hover {
  text-decoration: underline;
}
.loading-inline {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #94a3b8;
  font-size: 13px;
}
.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(99, 102, 241, 0.1);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s infinite linear;
}
.related-tasks-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.related-task-card {
  background: rgba(30, 41, 59, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s ease;
}
.related-task-card:hover {
  transform: translateY(-2px);
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(99, 102, 241, 0.3);
}
.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-no-lbl {
  font-family: monospace;
  font-weight: 600;
  color: #818cf8;
  background: rgba(99, 102, 241, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11.5px;
}
.task-type-lbl {
  font-size: 10.5px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 500;
}
.task-type-lbl.CASE_DESIGN { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.task-type-lbl.TEST_EXECUTION { background: rgba(16, 185, 129, 0.15); color: #34d399; }
.task-status-lbl {
  font-size: 10.5px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 500;
  margin-left: auto;
}
.task-status-lbl.draft { background: rgba(100, 116, 139, 0.1); color: #94a3b8; }
.task-status-lbl.ready { background: rgba(99, 102, 241, 0.1); color: #a5b4fc; }
.task-status-lbl.in_progress { background: rgba(245, 158, 11, 0.1); color: #fbbf24; }
.task-status-lbl.blocked { background: rgba(239, 68, 68, 0.1); color: #f87171; }
.task-status-lbl.completed { background: rgba(16, 185, 129, 0.1); color: #34d399; }
.task-status-lbl.cancelled { background: rgba(148, 163, 184, 0.1); color: #cbd5e1; }
.task-status-lbl.archived { background: rgba(120, 113, 108, 0.1); color: #a8a29e; }
.task-title-link {
  color: #f1f5f9;
  font-size: 13.5px;
  font-weight: 500;
  text-decoration: none;
}
.task-title-link:hover {
  color: #818cf8;
}
.card-bottom {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: #94a3b8;
  border-top: 1px dashed rgba(255, 255, 255, 0.04);
  padding-top: 8px;
}
.empty-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 50px 30px;
  color: #64748b;
  text-align: center;
  background: rgba(255, 255, 255, 0.01);
  border: 1px dashed rgba(255, 255, 255, 0.04);
  border-radius: 8px;
}
.icon-empty {
  font-size: 32px;
  margin-bottom: 10px;
}
.empty-placeholder p {
  margin: 0;
  font-size: 13px;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
