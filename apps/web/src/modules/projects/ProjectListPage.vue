<template>
  <div class="project-list-wrapper">
    <!-- 头部区域 -->
    <header class="header">
      <div class="brand">
        <span class="logo">TestWeave</span>
        <span class="divider">/</span>
        <span class="title">选择项目</span>
      </div>
      <div class="user-profile">
        <span class="user-name">{{ authStore.currentUser?.display_name }}</span>
        <button class="logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </header>

    <main class="container">
      <!-- 搜索和创建控制栏 -->
      <div class="control-bar">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="通过名称搜索项目..."
            @input="handleSearch"
          />
        </div>
        <button
          v-if="authStore.currentUser?.is_system_admin"
          class="create-btn"
          @click="showCreateModal = true"
        >
          + 新建项目
        </button>
      </div>

      <!-- 项目加载状态 -->
      <div v-if="isLoading" class="loading-state">
        <div class="skeleton-grid">
          <div v-for="i in 3" :key="i" class="skeleton-card"></div>
        </div>
      </div>

      <!-- 加载失败 -->
      <div v-else-if="errorMsg" class="error-state">
        <div class="err-icon">❌</div>
        <h3>加载项目失败</h3>
        <p>{{ errorMsg }}</p>
        <button class="retry-btn" @click="loadProjects">重试</button>
      </div>

      <!-- 空项目列表 -->
      <div v-else-if="filteredProjects.length === 0" class="empty-state">
        <div class="empty-icon">📁</div>
        <h3>未找到项目</h3>
        <p v-if="searchQuery">没有项目匹配 "{{ searchQuery }}"</p>
        <p v-else>您目前不属于任何项目，请联系系统管理员分配项目。</p>
      </div>

      <!-- 项目卡片网格 -->
      <div v-else class="project-grid">
        <div
          v-for="project in filteredProjects"
          :key="project.id"
          class="project-card"
          :class="{ archived: project.status === 'archived' }"
          @click="selectProject(project.id)"
        >
          <div class="card-header">
            <span class="project-avatar">{{ project.key }}</span>
            <span class="project-status" :class="project.status">
              {{ project.status === "archived" ? "已归档" : "活跃" }}
            </span>
          </div>
          <h3 class="project-name">{{ project.name }}</h3>
          <p class="project-desc">{{ project.description || "暂无项目描述。" }}</p>
          <div class="card-footer">
            <span class="member-role"
              >角色：{{
                project.role_id === "admin"
                  ? "项目管理员"
                  : project.role_id === "member"
                    ? "项目成员"
                    : project.role_id === "viewer"
                      ? "只读访客"
                      : "系统管理员"
              }}</span
            >
          </div>
        </div>
      </div>
    </main>

    <!-- 创建项目 Modal 弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-card">
        <h3>创建新项目</h3>
        <p class="modal-subtitle">初始化一个新的项目工作空间。</p>

        <form @submit.prevent="handleCreateProject">
          <div class="form-group">
            <label for="proj-key">项目标识 Key (2-10 位大写字母)</label>
            <input
              id="proj-key"
              v-model="createForm.key"
              type="text"
              required
              placeholder="例如 TW, DEMO"
              :disabled="isCreating"
              @input="formatKey"
            />
            <span class="field-hint">将作为测试用例的编号前缀（例如 TW-101）。</span>
          </div>

          <div class="form-group">
            <label for="proj-name">项目名称</label>
            <input
              id="proj-name"
              v-model="createForm.name"
              type="text"
              required
              placeholder="例如 TestWeave 核心系统"
              :disabled="isCreating"
            />
          </div>

          <div class="form-group">
            <label for="proj-desc">项目描述 (可选)</label>
            <textarea
              id="proj-desc"
              v-model="createForm.description"
              placeholder="请提供简短的项目介绍..."
              :disabled="isCreating"
            ></textarea>
          </div>

          <div v-if="createError" class="modal-error">
            <span>⚠️ {{ createError }}</span>
          </div>

          <div class="modal-actions">
            <button
              type="button"
              class="cancel-btn"
              :disabled="isCreating"
              @click="closeCreateModal"
            >
              取消
            </button>
            <button type="submit" class="submit-btn" :disabled="isCreating">
              <span v-if="isCreating" class="loader"></span>
              <span v-else>创建项目</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../../shared/stores/auth";
import { apiClient } from "../../shared/api/client";

interface ProjectItem {
  id: string;
  key: string;
  name: string;
  description: string;
  status: "active" | "archived";
  role_id: string | null;
  created_at: string;
}

const authStore = useAuthStore();
const router = useRouter();

const projectsList = ref<ProjectItem[]>([]);
const filteredProjects = ref<ProjectItem[]>([]);
const searchQuery = ref("");
const isLoading = ref(false);
const errorMsg = ref<string | null>(null);

// 创建项目弹窗控制
const showCreateModal = ref(false);
const isCreating = ref(false);
const createError = ref<string | null>(null);
const createForm = reactive({
  key: "",
  name: "",
  description: "",
});

function decodeProjects(value: unknown): ProjectItem[] {
  if (Array.isArray(value)) {
    return value.map((o: unknown) => {
      const item = o as Record<string, unknown>;
      return {
        id: String((item.id as string) ?? ""),
        key: String((item.key as string) ?? ""),
        name: String((item.name as string) ?? ""),
        description: String((item.description as string) ?? ""),
        status: item.status === "archived" ? "archived" : "active",
        role_id: typeof item.role_id === "string" ? item.role_id : null,
        created_at: String((item.created_at as string) ?? ""),
      };
    });
  }
  return [];
}

function decodeCreateResponse(value: unknown): { id: string } {
  if (typeof value === "object" && value !== null && "id" in value) {
    const o = value as Record<string, unknown>;
    return { id: typeof o.id === "string" ? o.id : "" };
  }
  throw new Error("无效的项目创建响应");
}

async function loadProjects(): Promise<void> {
  isLoading.value = true;
  errorMsg.value = null;
  try {
    const list = await apiClient.get("/api/v1/projects", decodeProjects);
    projectsList.value = list;
    applyFilter();
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : "获取项目列表失败。";
  } finally {
    isLoading.value = false;
  }
}

function applyFilter(): void {
  const query = searchQuery.value.trim().toLowerCase();
  if (!query) {
    filteredProjects.value = projectsList.value;
  } else {
    filteredProjects.value = projectsList.value.filter(
      (p) => p.name.toLowerCase().includes(query) || p.key.toLowerCase().includes(query),
    );
  }
}

function handleSearch(): void {
  applyFilter();
}

function formatKey(): void {
  // 仅允许字母，并自动转化为大写
  createForm.key = createForm.key.replace(/[^a-zA-Z]/g, "").toUpperCase();
}

function closeCreateModal(): void {
  showCreateModal.value = false;
  createForm.key = "";
  createForm.name = "";
  createForm.description = "";
  createError.value = null;
}

async function handleCreateProject(): Promise<void> {
  if (isCreating.value) return;

  // 校验 Key 长度 2-10 字符
  if (createForm.key.length < 2 || createForm.key.length > 10) {
    createError.value = "项目 Key 必须介于 2 到 10 个字符之间。";
    return;
  }

  isCreating.value = true;
  createError.value = null;

  try {
    const res = await apiClient.post("/api/v1/projects", decodeCreateResponse, {
      key: createForm.key,
      name: createForm.name,
      description: createForm.description,
    });

    closeCreateModal();
    // 创建成功，使用新 ID 引导进入工作台
    await router.push(`/projects/${res.id}/workbench`);
  } catch (e: unknown) {
    createError.value = e instanceof Error ? e.message : "创建项目失败。";
  } finally {
    isCreating.value = false;
  }
}

async function selectProject(projectId: string): Promise<void> {
  await router.push(`/projects/${projectId}/workbench`);
}

async function handleLogout(): Promise<void> {
  await authStore.logout();
  await router.push("/login");
}

onMounted(() => {
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  loadProjects();
});
</script>

<style scoped>
.project-list-wrapper {
  min-height: 100vh;
  background-color: #0b0f19;
  color: #f1f5f9;
  font-family:
    "Inter",
    system-ui,
    -apple-system,
    sans-serif;
  display: flex;
  flex-direction: column;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 40px;
  background-color: rgba(15, 23, 42, 0.8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  font-size: 20px;
  font-weight: 800;
  background: linear-gradient(135deg, #a5b4fc 0%, #818cf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.divider {
  color: #334155;
}

.title {
  color: #94a3b8;
  font-size: 14px;
  font-weight: 500;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-name {
  color: #cbd5e1;
  font-size: 14px;
}

.logout-btn {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.logout-btn:hover {
  border-color: #f87171;
  color: #f87171;
}

.container {
  flex: 1;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 40px;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  gap: 20px;
}

.search-box {
  position: relative;
  max-width: 400px;
  width: 100%;
  display: flex;
}

.search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
}

.search-box input {
  width: 100%;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 12px 16px 12px 40px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
}

.search-box input:focus {
  border-color: #6366f1;
}

.create-btn {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border: none;
  border-radius: 8px;
  color: #ffffff;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
  transition: all 0.2s ease;
}

.create-btn:hover {
  opacity: 0.95;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}

.project-card {
  background: rgba(30, 41, 59, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}

.project-card:hover {
  transform: translateY(-4px);
  border-color: rgba(99, 102, 241, 0.3);
  background: rgba(30, 41, 59, 0.5);
  box-shadow: 0 12px 20px -10px rgba(0, 0, 0, 0.3);
}

.project-card.archived {
  opacity: 0.65;
  border-color: rgba(245, 158, 11, 0.15);
}

.project-card.archived:hover {
  border-color: rgba(245, 158, 11, 0.3);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.project-avatar {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
  font-family: monospace;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  letter-spacing: 0.5px;
}

.project-status {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 12px;
  font-weight: 500;
  text-transform: capitalize;
}

.project-status.active {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.project-status.archived {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.2);
}

.project-name {
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
  margin: 0 0 10px 0;
}

.project-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
  flex: 1;
  margin: 0 0 20px 0;
}

.card-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  padding-top: 12px;
}

.member-role {
  color: #94a3b8;
  font-size: 12px;
}

/* 骨架屏加载状态 */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}

.skeleton-card {
  height: 200px;
  background: linear-gradient(
    90deg,
    rgba(30, 41, 59, 0.2) 25%,
    rgba(30, 41, 59, 0.4) 50%,
    rgba(30, 41, 59, 0.2) 75%
  );
  background-size: 200% 100%;
  animation: loading-skeleton 1.5s infinite;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

@keyframes loading-skeleton {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* 错误与空状态 */
.error-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 80px 40px;
}

.err-icon,
.empty-icon {
  font-size: 40px;
  margin-bottom: 16px;
}

h3 {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.error-state p,
.empty-state p {
  color: #64748b;
  font-size: 14px;
  max-width: 400px;
  margin-bottom: 24px;
}

.retry-btn {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 10px 24px;
  border-radius: 8px;
  cursor: pointer;
}

/* Modal 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 32px;
  max-width: 440px;
  width: 100%;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
}

.modal-subtitle {
  color: #64748b;
  font-size: 13px;
  margin-bottom: 24px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.form-group label {
  font-size: 12px;
  color: #94a3b8;
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
  min-height: 80px;
  resize: vertical;
}

.form-group input:focus,
.form-group textarea:focus {
  border-color: #6366f1;
}

.field-hint {
  font-size: 11px;
  color: #475569;
}

.modal-error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #f87171;
  font-size: 13px;
  padding: 10px;
  border-radius: 6px;
  margin-bottom: 20px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 28px;
}

.cancel-btn {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
}

.modal-actions .submit-btn {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
}

.modal-actions .submit-btn:disabled,
.cancel-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.loader {
  width: 14px;
  height: 14px;
  border: 2px solid #ffffff;
  border-bottom-color: transparent;
  border-radius: 50%;
  display: inline-block;
  animation: rotation 1s linear infinite;
}

@keyframes rotation {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}
</style>
