<template>
  <div class="versions-wrapper">
    <!-- 头部和搜索控制栏 -->
    <div class="control-header">
      <div class="search-filters">
        <div class="search-box">
          <span class="icon">🔍</span>
          <input
            v-model="filters.name_or_key"
            type="text"
            placeholder="搜索版本名称或标识..."
            @input="debounceSearch"
          />
        </div>
        <div class="select-group">
          <select v-model="filters.status" @change="void fetchVersions()">
            <option value="">所有状态</option>
            <option value="PLANNING">规划中</option>
            <option value="ACTIVE">进行中</option>
            <option value="TESTING">测试中</option>
            <option value="RELEASED">已发布</option>
            <option value="ARCHIVED">已归档</option>
          </select>
          <select v-model="filters.owner_id" @change="void fetchVersions()">
            <option value="">所有负责人</option>
            <option v-for="m in members" :key="m.user_id" :value="m.user_id">
              {{ m.display_name }} ({{ m.username }})
            </option>
          </select>
        </div>
      </div>
      <button
        v-if="projectStore.hasPermission('version.manage')"
        class="create-btn"
        @click="openCreateDrawer"
      >
        + 新建版本
      </button>
    </div>

    <!-- 加载与错误状态 -->
    <div v-if="isLoading" class="loading-state">
      <div class="loading-spinner"></div>
      <p>正在努力加载版本台账...</p>
    </div>

    <div v-else-if="errorMsg" class="error-state">
      <span class="err-icon">⚠️</span>
      <p>加载版本列表失败: {{ errorMsg }}</p>
      <button @click="void fetchVersions()">重试</button>
    </div>

    <div v-else-if="versions.length === 0" class="empty-state">
      <span class="empty-icon">🏷️</span>
      <h3>暂无版本记录</h3>
      <p>没有找到与过滤条件匹配的测试版本。</p>
    </div>

    <!-- 版本表格 -->
    <div v-else class="table-container">
      <table class="versions-table">
        <thead>
          <tr>
            <th>版本名称</th>
            <th>版本标识</th>
            <th>状态</th>
            <th>负责人</th>
            <th>计划开始</th>
            <th>计划结束</th>
            <th>更新时间</th>
            <th class="actions-col" v-if="projectStore.hasPermission('version.manage')">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in versions" :key="v.id" :class="{ archived: v.status === 'ARCHIVED' }">
            <td>
              <router-link :to="`/projects/${projectId}/versions/${v.id}`" class="version-link">
                {{ v.name }}
              </router-link>
            </td>
            <td>
              <span class="version-key-badge">{{ v.key }}</span>
            </td>
            <td>
              <span :class="['status-badge', v.status.toLowerCase()]">
                {{ formatStatus(v.status) }}
              </span>
            </td>
            <td>{{ getUserDisplayName(v.ownerId) }}</td>
            <td>{{ formatDate(v.plannedStartAt) }}</td>
            <td>{{ formatDate(v.plannedEndAt) }}</td>
            <td>{{ formatTime(v.updatedAt) }}</td>
            <td class="actions-cell" v-if="projectStore.hasPermission('version.manage')">
              <button class="action-btn edit" @click="openEditDrawer(v)">编辑</button>
              <button
                v-if="v.status !== 'ARCHIVED'"
                class="action-btn archive"
                @click="confirmArchive(v)"
              >
                归档
              </button>
              <button v-else class="action-btn restore" @click="void handleRestore(v)">恢复</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 创建/编辑抽屉 (Drawer) -->
    <div v-if="drawer.visible" class="drawer-overlay" @click.self="closeDrawer">
      <div class="drawer-panel">
        <div class="drawer-header">
          <h3>{{ drawer.isEdit ? "编辑版本信息" : "新建测试版本" }}</h3>
          <button class="close-btn" @click="closeDrawer">×</button>
        </div>

        <form class="drawer-form" @submit.prevent="void submitForm()">
          <div class="form-group">
            <label for="v-key">版本标识 Key *</label>
            <input
              id="v-key"
              v-model="form.key"
              type="text"
              required
              placeholder="例如 v1.0.0"
              :disabled="drawer.isEdit || isSaving"
            />
            <span class="hint">创建后不可修改，项目内唯一。</span>
          </div>

          <div class="form-group">
            <label for="v-name">版本名称 *</label>
            <input
              id="v-name"
              v-model="form.name"
              type="text"
              required
              placeholder="例如 v1.0.0 支付宝支付上线"
              :disabled="isSaving"
            />
          </div>

          <div class="form-group">
            <label for="v-owner">负责人 *</label>
            <select id="v-owner" v-model="form.owner_id" required :disabled="isSaving">
              <option value="">请选择项目成员...</option>
              <option v-for="m in members" :key="m.user_id" :value="m.user_id">
                {{ m.display_name }} ({{ m.username }})
              </option>
            </select>
          </div>

          <div v-if="drawer.isEdit" class="form-group">
            <label for="v-status">版本状态 *</label>
            <select id="v-status" v-model="form.status" required :disabled="isSaving">
              <option value="PLANNING">规划中</option>
              <option value="ACTIVE">进行中</option>
              <option value="TESTING">测试中</option>
              <option value="RELEASED">已发布</option>
            </select>
          </div>

          <div class="form-group row">
            <div class="col">
              <label for="v-start">计划开始时间</label>
              <input
                id="v-start"
                v-model="form.planned_start_at"
                type="date"
                :disabled="isSaving"
              />
            </div>
            <div class="col">
              <label for="v-end">计划结束时间</label>
              <input id="v-end" v-model="form.planned_end_at" type="date" :disabled="isSaving" />
            </div>
          </div>

          <div class="form-group">
            <label for="v-desc">版本描述说明</label>
            <textarea
              id="v-desc"
              v-model="form.description"
              placeholder="说明此版本的迭代范围、目标或注意事项..."
              :disabled="isSaving"
            ></textarea>
          </div>

          <div v-if="saveError" class="error-banner">⚠️ {{ saveError }}</div>

          <div class="drawer-actions">
            <button type="button" class="cancel-btn" :disabled="isSaving" @click="closeDrawer">
              取消
            </button>
            <button type="submit" class="submit-btn" :disabled="isSaving">
              {{ isSaving ? "正在保存..." : "提交保存" }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 归档确认 Dialog -->
    <div v-if="dialog.visible" class="dialog-overlay" @click.self="closeDialog">
      <div class="dialog-panel">
        <h4>确认要归档此版本吗？</h4>
        <p class="warning-text">
          版本
          <strong>{{ dialog.version?.name }}</strong>
          归档后将处于<strong>只读状态</strong>，默认不在活跃版本列表中展示，且不允许新增或移出需求。
        </p>
        <div class="dialog-actions">
          <button class="cancel-btn" @click="closeDialog">我再想想</button>
          <button class="confirm-btn" @click="void handleArchive()">确认归档</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from "vue";
import { useRoute } from "vue-router";
import { useProjectStore } from "../../shared/stores/project";
import { versionsApi, type Version } from "./api";
import { apiClient } from "../../shared/api/client";

interface Member {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
}

const route = useRoute();
const projectStore = useProjectStore();
const projectId = route.params.projectId as string;

// 数据定义
const versions = ref<Version[]>([]);
const members = ref<Member[]>([]);
const isLoading = ref(false);
const errorMsg = ref<string | null>(null);

// 搜索筛选过滤
const filters = reactive({
  name_or_key: "",
  status: "",
  owner_id: "",
});

let searchTimeout: ReturnType<typeof setTimeout> | null = null;
function debounceSearch() {
  if (searchTimeout) clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    void fetchVersions();
  }, 350);
}

// 加载成员列表 (用于下拉列表)
async function fetchMembers() {
  try {
    const data = await apiClient.get(
      `/api/v1/projects/${projectId}/members`,
      (val) => val as Member[],
    );
    members.value = data;
  } catch (e: unknown) {
    const err = e as { message?: string };
    console.error("加载成员列表失败", err.message);
  }
}

// 加载版本台账
async function fetchVersions() {
  isLoading.value = true;
  errorMsg.value = null;
  try {
    const res = await versionsApi.list(projectId, {
      name_or_key: filters.name_or_key,
      status: filters.status,
      owner_id: filters.owner_id,
      limit: 100,
      offset: 0,
    });
    versions.value = res.items;
  } catch (e: unknown) {
    const err = e as { message?: string };
    errorMsg.value = err.message || "请求服务器发生网络错误";
  } finally {
    isLoading.value = false;
  }
}

// 辅助方法
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

function getUserDisplayName(userId: string) {
  const m = members.value.find((x) => x.user_id === userId);
  return m ? m.display_name : "未分配";
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return "-";
  return dateStr.substring(0, 10);
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// 表单与抽屉 (Drawer) 逻辑
const drawer = reactive({
  visible: false,
  isEdit: false,
  versionId: "",
  rowVersion: 1,
});

const form = reactive({
  key: "",
  name: "",
  description: "",
  owner_id: "",
  status: "PLANNING",
  planned_start_at: "",
  planned_end_at: "",
});

const isSaving = ref(false);
const saveError = ref<string | null>(null);

function openCreateDrawer() {
  saveError.value = null;
  drawer.visible = true;
  drawer.isEdit = false;

  form.key = "";
  form.name = "";
  form.description = "";
  form.owner_id = "";
  form.status = "PLANNING";
  form.planned_start_at = "";
  form.planned_end_at = "";
}

function openEditDrawer(v: Version) {
  saveError.value = null;
  drawer.visible = true;
  drawer.isEdit = true;
  drawer.versionId = v.id;
  drawer.rowVersion = v.rowVersion;

  form.key = v.key;
  form.name = v.name;
  form.description = v.description || "";
  form.owner_id = v.ownerId;
  form.status = v.status;
  form.planned_start_at = v.plannedStartAt ? v.plannedStartAt.substring(0, 10) : "";
  form.planned_end_at = v.plannedEndAt ? v.plannedEndAt.substring(0, 10) : "";
}

function closeDrawer() {
  drawer.visible = false;
}

async function submitForm() {
  isSaving.value = true;
  saveError.value = null;

  const startVal = form.planned_start_at ? new Date(form.planned_start_at).toISOString() : null;
  const endVal = form.planned_end_at ? new Date(form.planned_end_at).toISOString() : null;

  try {
    if (drawer.isEdit) {
      await versionsApi.update(projectId, drawer.versionId, {
        name: form.name,
        description: form.description,
        owner_id: form.owner_id,
        status: form.status,
        planned_start_at: startVal,
        planned_end_at: endVal,
        rowVersion: drawer.rowVersion,
      });
    } else {
      await versionsApi.create(projectId, {
        key: form.key,
        name: form.name,
        description: form.description,
        owner_id: form.owner_id,
        planned_start_at: startVal,
        planned_end_at: endVal,
      });
    }
    drawer.visible = false;
    void fetchVersions();
  } catch (e: unknown) {
    const err = e as { message?: string };
    saveError.value = err.message || "保存版本失败，请检查数据合法性。";
  } finally {
    isSaving.value = false;
  }
}

// 归档弹窗与恢复逻辑
const dialog = reactive({
  visible: false,
  version: null as Version | null,
});

function confirmArchive(v: Version) {
  dialog.visible = true;
  dialog.version = v;
}

function closeDialog() {
  dialog.visible = false;
  dialog.version = null;
}

async function handleArchive() {
  if (!dialog.version) return;
  try {
    await versionsApi.archive(projectId, dialog.version.id);
    closeDialog();
    void fetchVersions();
  } catch (e: unknown) {
    const err = e as { message?: string };
    alert(err.message || "归档失败");
  }
}

async function handleRestore(v: Version) {
  try {
    await versionsApi.restore(projectId, v.id);
    void fetchVersions();
  } catch (e: unknown) {
    const err = e as { message?: string };
    alert(err.message || "恢复失败");
  }
}

onMounted(() => {
  void fetchMembers();
  void fetchVersions();
});
</script>

<style scoped>
.versions-wrapper {
  padding: 24px;
  color: #f1f5f9;
}

.control-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.search-filters {
  display: flex;
  gap: 16px;
  flex: 1;
  max-width: 720px;
}

.search-box {
  position: relative;
  flex: 1;
}

.search-box input {
  width: 100%;
  padding: 10px 14px 10px 38px;
  background: rgba(30, 41, 59, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: #f1f5f9;
  font-size: 14px;
  transition: all 0.3s ease;
}

.search-box input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.search-box .icon {
  position: absolute;
  left: 12px;
  top: 10px;
  font-size: 14px;
  opacity: 0.5;
}

.select-group {
  display: flex;
  gap: 12px;
}

.select-group select {
  padding: 10px 14px;
  background: rgba(30, 41, 59, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
  cursor: pointer;
}

.create-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 500;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
  transition:
    transform 0.2s,
    box-shadow 0.2s;
}

.create-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}

.table-container {
  background: rgba(30, 41, 59, 0.2);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
}

.versions-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 14px;
}

.versions-table th {
  background: rgba(15, 23, 42, 0.4);
  padding: 14px 20px;
  font-weight: 600;
  color: #94a3b8;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.versions-table td {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.versions-table tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

.versions-table tr.archived {
  opacity: 0.5;
}

.version-link {
  color: #6366f1;
  text-decoration: none;
  font-weight: 500;
  cursor: pointer;
}

.version-link:hover {
  text-decoration: underline;
  color: #818cf8;
}

.version-key-badge {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  color: #cbd5e1;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
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

.actions-col {
  text-align: right;
}

.actions-cell {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.action-btn {
  background: transparent;
  border: none;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.action-btn.edit {
  color: #60a5fa;
}
.action-btn.edit:hover {
  background: rgba(96, 165, 250, 0.1);
}

.action-btn.archive {
  color: #f87171;
}
.action-btn.archive:hover {
  background: rgba(248, 113, 113, 0.1);
}

.action-btn.restore {
  color: #34d399;
}
.action-btn.restore:hover {
  background: rgba(52, 211, 153, 0.1);
}

/* 抽屉 Panel */
.drawer-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.drawer-panel {
  width: 100%;
  max-width: 480px;
  height: 100%;
  background: #1e293b;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.drawer-header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.drawer-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}

.close-btn {
  background: transparent;
  border: none;
  font-size: 24px;
  color: #94a3b8;
  cursor: pointer;
}

.close-btn:hover {
  color: #f1f5f9;
}

.drawer-form {
  padding: 24px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group.row {
  flex-direction: row;
  gap: 16px;
}

.form-group.row .col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
}

.form-group input,
.form-group select,
.form-group textarea {
  padding: 10px 12px;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  border-color: #6366f1;
}

.form-group input:disabled,
.form-group select:disabled,
.form-group textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-group textarea {
  height: 100px;
  resize: vertical;
}

.form-group .hint {
  font-size: 12px;
  color: #64748b;
}

.error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 12px;
  border-radius: 6px;
  color: #f87171;
  font-size: 13px;
}

.drawer-actions {
  margin-top: auto;
  padding-top: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.drawer-actions .cancel-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.drawer-actions .cancel-btn:hover {
  background: rgba(255, 255, 255, 0.03);
}

.drawer-actions .submit-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.drawer-actions .submit-btn:hover {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

/* Dialog Overlay */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 110;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-panel {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.dialog-panel h4 {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
}

.dialog-panel .warning-text {
  font-size: 13px;
  color: #94a3b8;
  line-height: 1.6;
  margin-bottom: 24px;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.dialog-actions button {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.dialog-actions .cancel-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
}

.dialog-actions .confirm-btn {
  background: #ef4444;
  border: none;
  color: #ffffff;
}

.dialog-actions .confirm-btn:hover {
  background: #dc2626;
}

/* 状态加载样式 */
.loading-state,
.error-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  background: rgba(30, 41, 59, 0.15);
  border: 1px dashed rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  text-align: center;
  padding: 40px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(99, 102, 241, 0.1);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 16px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.err-icon,
.empty-icon {
  font-size: 36px;
  margin-bottom: 16px;
}

.error-state button {
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.empty-state h3 {
  margin: 0 0 8px;
  font-size: 16px;
}

.empty-state p {
  color: #64748b;
  font-size: 13px;
  margin: 0;
}
</style>
