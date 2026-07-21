<template>
  <div class="admin-settings-container">
    <!-- 顶部状态栏 -->
    <div class="admin-header">
      <h2>项目设置与管理</h2>
      <p class="subtitle">管理项目详情、成员角色与操作审计日志。</p>
    </div>

    <!-- 主布局网格 -->
    <div class="admin-grid">
      <!-- 1. 项目基本信息管理 -->
      <section class="admin-card">
        <h3>📂 项目信息</h3>
        <p class="card-desc">编辑项目名称、描述及状态。</p>

        <form @submit.prevent="handleUpdateProject">
          <div class="form-group">
            <label for="p-name">项目名称</label>
            <input
              id="p-name"
              v-model="projectForm.name"
              type="text"
              required
              :disabled="isArchived || isUpdating"
            />
          </div>

          <div class="form-group">
            <label for="p-desc">项目描述</label>
            <textarea
              id="p-desc"
              v-model="projectForm.description"
              :disabled="isArchived || isUpdating"
            ></textarea>
          </div>

          <div v-if="updateError" class="error-text">⚠️ {{ updateError }}</div>
          <div v-if="updateSuccess" class="success-text">✓ 项目信息更新成功！</div>

          <div class="form-actions">
            <!-- 归档项目按钮 -->
            <button
              v-if="!isArchived"
              type="button"
              class="archive-btn"
              :disabled="isUpdating"
              @click="handleArchiveProject"
            >
              归档项目
            </button>
            <span v-else class="archived-tag">🔒 已归档（只读）</span>

            <button type="submit" class="save-btn" :disabled="isArchived || isUpdating">
              {{ isUpdating ? "保存中..." : "保存更改" }}
            </button>
          </div>
        </form>
      </section>

      <!-- 2. 项目成员管理 -->
      <section class="admin-card wide">
        <h3>👥 项目成员</h3>
        <p class="card-desc">分配项目角色并管理项目工作空间的访问权限。</p>

        <!-- 添加成员表单 (若归档则隐藏/置灰) -->
        <div v-if="!isArchived" class="add-member-section">
          <div class="add-member-inputs">
            <input
              v-model="addMemberForm.userId"
              type="text"
              placeholder="请输入用户 ID (UUID)..."
              required
            />
            <select v-model="addMemberForm.roleId">
              <option value="project_admin">项目管理员</option>
              <option value="test_lead">测试主管</option>
              <option value="test_member">测试人员</option>
              <option value="guest">只读访客</option>
            </select>
            <button class="add-btn" :disabled="isMemberLoading" @click="handleAddMember">
              添加成员
            </button>
          </div>
          <!-- 复制自己的 ID 提示，方便测试 -->
          <div class="my-id-hint" @click="copyMyId">
            💡 点击复制我的用户 ID (测试用)：<code>{{ authStore.currentUser?.id }}</code>
          </div>
          <div v-if="memberError" class="error-text member-err">⚠️ {{ memberError }}</div>
        </div>

        <!-- 成员列表表格 -->
        <div class="members-table-wrapper">
          <table class="members-table">
            <thead>
              <tr>
                <th>姓名</th>
                <th>用户名</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th v-if="!isArchived">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in members" :key="m.user_id">
                <td>
                  <div class="member-name-cell">
                    <span class="member-avatar">👤</span>
                    <span>{{ m.display_name }}</span>
                  </div>
                </td>
                <td class="mono">{{ m.username }}</td>
                <td>{{ m.email }}</td>
                <td>
                  <select
                    v-model="m.role_id"
                    :disabled="isArchived || isMemberLoading"
                    class="role-select"
                    @change="handleRoleChange(m.user_id, m.role_id)"
                  >
                    <option value="project_admin">项目管理员</option>
                    <option value="test_lead">测试主管</option>
                    <option value="test_member">测试人员</option>
                    <option value="guest">只读访客</option>
                  </select>
                </td>
                <td>
                  <span class="status-dot" :class="m.status"></span>
                  {{ m.status === "active" ? "正常" : "禁用" }}
                </td>
                <td v-if="!isArchived">
                  <button
                    class="remove-btn"
                    :disabled="isMemberLoading"
                    @click="handleRemoveMember(m.user_id)"
                  >
                    移出
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 3. 操作审计日志 -->
      <section class="admin-card wide">
        <h3>📜 项目审计日志</h3>
        <p class="card-desc">查看该项目中管理操作的完整时间线。</p>

        <!-- 审计日志时间线 -->
        <div v-if="isAuditLoading" class="audit-loading">加载审计日志中...</div>
        <div v-else-if="auditLogs.length === 0" class="audit-empty">
          该项目目前暂无操作审计日志记录。
        </div>
        <div v-else class="audit-timeline">
          <div v-for="log in auditLogs" :key="log.id" class="timeline-event">
            <div class="event-marker"></div>
            <div class="event-content">
              <div class="event-header">
                <span class="event-action">{{ log.action.toUpperCase() }}</span>
                <span class="event-time">{{ formatTime(log.timestamp) }}</span>
              </div>
              <p class="event-summary">{{ log.summary }}</p>
              <div class="event-meta">
                <span>操作人 ID: {{ log.actor_id }}</span>
                <span class="meta-divider">|</span>
                <span>请求 ID: {{ log.request_id }}</span>
              </div>
            </div>
          </div>

          <!-- 分页控制器 -->
          <div class="pagination">
            <button
              class="page-btn"
              :disabled="currentPage === 1"
              @click="changePage(currentPage - 1)"
            >
              上一页
            </button>
            <span class="page-indicator">第 {{ currentPage }} 页</span>
            <button
              class="page-btn"
              :disabled="auditLogs.length < pageSize"
              @click="changePage(currentPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../../shared/stores/auth";
import { useProjectStore } from "../../shared/stores/project";
import { apiClient } from "../../shared/api/client";

interface MemberItem {
  user_id: string;
  username: string;
  email: string;
  display_name: string;
  role_id: string;
  status: "active" | "inactive";
  joined_at: string;
}

interface AuditLogItem {
  id: string;
  action: string;
  object_type: string;
  object_id: string;
  summary: string;
  timestamp: string;
  actor_id: string;
  request_id: string;
}

const router = useRouter();
const authStore = useAuthStore();
const projectStore = useProjectStore();

// 1. 项目详情与更新
const projectForm = reactive({
  name: "",
  description: "",
});
const isUpdating = ref(false);
const updateError = ref<string | null>(null);
const updateSuccess = ref(false);

const isArchived = computed(() => {
  return projectStore.currentProject?.status === "archived";
});

// 2. 成员管理
const members = ref<MemberItem[]>([]);
const isMemberLoading = ref(false);
const memberError = ref<string | null>(null);
const addMemberForm = reactive({
  userId: "",
  roleId: "test_member",
});

// 3. 审计日志分页
const auditLogs = ref<AuditLogItem[]>([]);
const isAuditLoading = ref(false);
const currentPage = ref(1);
const pageSize = 10;

function decodeProjectDetail(value: unknown): { name: string; description: string } {
  if (typeof value === "object" && value !== null) {
    const o = value as Record<string, unknown>;
    return {
      name: String((o.name as string) ?? ""),
      description: String((o.description as string) ?? ""),
    };
  }
  return { name: "", description: "" };
}

function decodeMembers(value: unknown): MemberItem[] {
  if (Array.isArray(value)) {
    return value.map((o: unknown) => {
      const item = o as Record<string, unknown>;
      return {
        user_id: String((item.user_id as string) ?? ""),
        username: String((item.username as string) ?? ""),
        email: String((item.email as string) ?? ""),
        display_name: String((item.display_name as string) ?? ""),
        role_id: String((item.role_id as string) ?? ""),
        status: item.status === "inactive" ? "inactive" : "active",
        joined_at: String((item.joined_at as string) ?? ""),
      };
    });
  }
  return [];
}

function decodeMemberResponse(value: unknown): MemberItem {
  if (typeof value === "object" && value !== null) {
    const o = value as Record<string, unknown>;
    return {
      user_id: String((o.user_id as string) ?? ""),
      username: String((o.username as string) ?? ""),
      email: String((o.email as string) ?? ""),
      display_name: String((o.display_name as string) ?? ""),
      role_id: String((o.role_id as string) ?? ""),
      status: o.status === "inactive" ? "inactive" : "active",
      joined_at: String((o.joined_at as string) ?? ""),
    };
  }
  throw new Error("无效的成员响应");
}

function decodeAuditLogs(value: unknown): AuditLogItem[] {
  if (Array.isArray(value)) {
    return value.map((o: unknown) => {
      const item = o as Record<string, unknown>;
      return {
        id: String((item.id as string) ?? ""),
        action: String((item.action as string) ?? ""),
        object_type: String((item.object_type as string) ?? ""),
        object_id: String((item.object_id as string) ?? ""),
        summary: String((item.summary as string) ?? ""),
        timestamp: String((item.timestamp as string) ?? ""),
        actor_id: String((item.actor_id as string) ?? ""),
        request_id: String((item.request_id as string) ?? ""),
      };
    });
  }
  return [];
}

async function loadProjectDetails(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  try {
    const detail = await apiClient.get(`/api/v1/projects/${projectId}`, decodeProjectDetail);
    projectForm.name = detail.name;
    projectForm.description = detail.description;
  } catch {
    // 降级使用 store 数据
    projectForm.name = projectStore.currentProject?.name || "";
    projectForm.description = projectStore.currentProject?.description || "";
  }
}

async function handleUpdateProject(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId || isArchived.value) return;

  isUpdating.value = true;
  updateError.value = null;
  updateSuccess.value = false;

  try {
    await apiClient.patch(`/api/v1/projects/${projectId}`, decodeProjectDetail, {
      name: projectForm.name,
      description: projectForm.description,
    });
    updateSuccess.value = true;
    // 刷新项目上下文以更新 sidebar 展示
    await projectStore.loadProjectContext(projectId);
  } catch (e: unknown) {
    updateError.value = e instanceof Error ? e.message : "更新项目信息失败。";
  } finally {
    isUpdating.value = false;
  }
}

async function handleArchiveProject(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId || isArchived.value) return;

  if (!confirm("您确定要归档此项目吗？这会使项目进入只读状态，并禁用所有的写入操作。")) {
    return;
  }

  isUpdating.value = true;
  updateError.value = null;

  try {
    await apiClient.post(`/api/v1/projects/${projectId}/archive`, decodeProjectDetail);
    // 刷新项目状态
    await projectStore.loadProjectContext(projectId);
    updateSuccess.value = true;
  } catch (e: unknown) {
    updateError.value = e instanceof Error ? e.message : "归档项目失败。";
  } finally {
    isUpdating.value = false;
  }
}

// 成员拉取与管理
async function fetchMembers(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  try {
    const list = await apiClient.get(`/api/v1/projects/${projectId}/members`, decodeMembers);
    members.value = list;
  } catch (e: unknown) {
    memberError.value = e instanceof Error ? e.message : "获取项目成员失败。";
  }
}

async function handleAddMember(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId || isArchived.value || !addMemberForm.userId) return;

  isMemberLoading.value = true;
  memberError.value = null;

  try {
    await apiClient.post(`/api/v1/projects/${projectId}/members`, decodeMemberResponse, {
      user_id: addMemberForm.userId,
      role_id: addMemberForm.roleId,
    });
    addMemberForm.userId = "";
    await fetchMembers();
    await fetchAuditLogs();
  } catch (e: unknown) {
    memberError.value = e instanceof Error ? e.message : "添加成员失败。";
  } finally {
    isMemberLoading.value = false;
  }
}

async function handleRoleChange(userId: string, newRoleId: string): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId || isArchived.value) return;

  // 在 UI 层面做警告提示（保护最后一名管理员），但仍可以发送以验证后端最终拦截
  const adminCount = members.value.filter((m) => m.role_id === "project_admin").length;
  const targetMember = members.value.find((m) => m.user_id === userId);

  if (
    targetMember &&
    targetMember.role_id === "project_admin" &&
    newRoleId !== "project_admin" &&
    adminCount <= 1
  ) {
    if (
      !confirm(
        "⚠️ 警告：您正在修改唯一的项目管理员角色。此操作可能会导致您失去管理员管理权限，是否继续？",
      )
    ) {
      await fetchMembers(); // 重置下拉选择
      return;
    }
  }

  isMemberLoading.value = true;
  memberError.value = null;

  try {
    await apiClient.patch(`/api/v1/projects/${projectId}/members/${userId}`, decodeMemberResponse, {
      role_id: newRoleId,
    });
    await fetchMembers();
    await fetchAuditLogs();

    // 如果当前操作人被降级，则重新加载上下文
    if (userId === authStore.currentUser?.id) {
      await projectStore.loadProjectContext(projectId);
    }
  } catch (e: unknown) {
    memberError.value = e instanceof Error ? e.message : "更新成员角色失败。";
    await fetchMembers(); // 刷新恢复真实角色
  } finally {
    isMemberLoading.value = false;
  }
}

async function handleRemoveMember(userId: string): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId || isArchived.value) return;

  const adminCount = members.value.filter((m) => m.role_id === "project_admin").length;
  const targetMember = members.value.find((m) => m.user_id === userId);

  if (targetMember && targetMember.role_id === "project_admin" && adminCount <= 1) {
    if (!confirm("⚠️ 警告：您正在移除唯一的项目管理员，是否继续？")) {
      return;
    }
  }

  if (!confirm("您确定要从项目中移除此成员吗？")) {
    return;
  }

  isMemberLoading.value = true;
  memberError.value = null;

  try {
    await apiClient.delete(`/api/v1/projects/${projectId}/members/${userId}`, decodeMemberResponse);
    await fetchMembers();
    await fetchAuditLogs();

    // 如果当前操作人自己被移除了，立刻被项目守卫驱逐并返回项目选择列表
    if (userId === authStore.currentUser?.id) {
      projectStore.reset();
      await router.push("/projects");
    }
  } catch (e: unknown) {
    memberError.value = e instanceof Error ? e.message : "移除成员失败。";
  } finally {
    isMemberLoading.value = false;
  }
}

// 审计日志
async function fetchAuditLogs(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;

  isAuditLoading.value = true;
  const offset = (currentPage.value - 1) * pageSize;

  try {
    const list = await apiClient.get(
      `/api/v1/projects/${projectId}/audit-events?limit=${pageSize}&offset=${offset}`,
      decodeAuditLogs,
    );
    auditLogs.value = list;
  } catch {
    auditLogs.value = [];
  } finally {
    isAuditLoading.value = false;
  }
}

async function changePage(page: number): Promise<void> {
  currentPage.value = page;
  await fetchAuditLogs();
}

function formatTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleString();
  } catch {
    return isoStr;
  }
}

function copyMyId(): void {
  const id = authStore.currentUser?.id;
  if (id) {
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    navigator.clipboard.writeText(id);
    alert("用户 ID 已成功复制到剪贴板！");
  }
}

// 监听项目切换，刷新所有页面数据
watch(
  () => projectStore.currentProjectId,
  (newId) => {
    if (newId) {
      // eslint-disable-next-line @typescript-eslint/no-floating-promises
      loadProjectDetails();
      // eslint-disable-next-line @typescript-eslint/no-floating-promises
      fetchMembers();
      currentPage.value = 1;
      // eslint-disable-next-line @typescript-eslint/no-floating-promises
      fetchAuditLogs();
    }
  },
);

onMounted(() => {
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  loadProjectDetails();
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  fetchMembers();
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  fetchAuditLogs();
});
</script>

<style scoped>
.admin-settings-container {
  display: flex;
  flex-direction: column;
  gap: 28px;
  width: 100%;
}

.admin-header h2 {
  color: #f1f5f9;
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 6px;
}

.subtitle {
  color: #64748b;
  font-size: 14px;
}

.admin-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px;
}

.admin-card {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 28px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
  box-sizing: border-box;
}

.admin-card.wide {
  grid-column: span 2;
}

h3 {
  color: #f1f5f9;
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 6px 0;
}

.card-desc {
  color: #94a3b8;
  font-size: 13px;
  margin: 0 0 24px 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.form-group label {
  color: #94a3b8;
  font-size: 12px;
}

.form-group input,
.form-group textarea {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 12px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}

.form-group textarea {
  min-height: 90px;
  resize: vertical;
}

.form-group input:focus,
.form-group textarea:focus {
  border-color: #6366f1;
}

.form-group input:disabled,
.form-group textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-text {
  color: #f87171;
  font-size: 13px;
  margin-bottom: 16px;
}

.success-text {
  color: #34d399;
  font-size: 13px;
  margin-bottom: 16px;
}

.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 24px;
}

.save-btn {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 600;
  cursor: pointer;
}

.save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.archive-btn {
  background: none;
  border: 1px solid #d97706;
  color: #fbbf24;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.archive-btn:hover {
  background: rgba(217, 119, 6, 0.15);
}

.archived-tag {
  color: #fbbf24;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid rgba(245, 158, 11, 0.3);
  padding: 8px 16px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.08);
}

/* 成员管理区 */
.add-member-section {
  background: rgba(15, 23, 42, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.04);
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 24px;
}

.add-member-inputs {
  display: flex;
  gap: 12px;
}

.add-member-inputs input {
  flex: 1;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 10px 14px;
  color: #f1f5f9;
  font-size: 13px;
  outline: none;
}

.add-member-inputs select {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 10px 14px;
  color: #cbd5e1;
  font-size: 13px;
  outline: none;
}

.add-btn {
  background: #6366f1;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-weight: 600;
  cursor: pointer;
}

.my-id-hint {
  margin-top: 12px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  display: inline-block;
}

.my-id-hint code {
  color: #a5b4fc;
  font-family: monospace;
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 4px;
}

.my-id-hint:hover code {
  text-decoration: underline;
}

.member-err {
  margin-top: 12px;
  margin-bottom: 0;
}

.members-table-wrapper {
  overflow-x: auto;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.members-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 13px;
}

.members-table th {
  background: rgba(15, 23, 42, 0.6);
  color: #94a3b8;
  font-weight: 600;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.members-table td {
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
}

.member-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.member-avatar {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.mono {
  font-family: monospace;
}

.role-select {
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  outline: none;
}

.role-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
}

.status-dot.active {
  background-color: #10b981;
}

.status-dot.inactive {
  background-color: #ef4444;
}

.remove-btn {
  background: none;
  border: 1px solid rgba(239, 68, 68, 0.15);
  color: #f87171;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.remove-btn:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: #ef4444;
}

/* 审计日志时间线 */
.audit-timeline {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.timeline-event {
  display: flex;
  gap: 16px;
  position: relative;
}

.event-marker {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6366f1;
  margin-top: 5px;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.15);
  flex-shrink: 0;
}

.event-content {
  background: rgba(15, 23, 42, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.04);
  padding: 16px 20px;
  border-radius: 12px;
  flex: 1;
}

.event-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.event-action {
  font-size: 11px;
  font-weight: 700;
  color: #818cf8;
  letter-spacing: 0.5px;
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
}

.event-time {
  color: #475569;
  font-size: 11px;
}

.event-summary {
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.5;
  margin: 0 0 10px 0;
}

.event-meta {
  color: #475569;
  font-size: 11px;
  display: flex;
  gap: 8px;
}

.meta-divider {
  color: #1e293b;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  margin-top: 20px;
}

.page-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-indicator {
  font-size: 13px;
  color: #64748b;
}
</style>
