<template>
  <div class="repo-settings-container">
    <div class="page-header">
      <h2>📦 代码仓库配置</h2>
      <p class="subtitle">配置项目代码仓库，供 AI 自动关联提交记录并分析代码变动差异。</p>
    </div>

    <!-- 主配置卡片 -->
    <div class="glass-card">
      <div v-if="loading" class="loading-state">
        <span class="spinner">⏳</span> 加载仓库配置中...
      </div>

      <form v-else @submit.prevent="void handleSave()">
        <!-- 仓库基本信息 -->
        <div class="section-title">基本信息</div>
        <div class="form-row">
          <div class="form-group half">
            <label for="repoName">仓库名称 <span class="required">*</span></label>
            <input
              id="repoName"
              v-model="form.name"
              type="text"
              placeholder="例如: 主代码库"
              required
            />
          </div>
          <div class="form-group half">
            <label for="mainBranch">主干分支 <span class="required">*</span></label>
            <input
              id="mainBranch"
              v-model="form.main_branch"
              type="text"
              placeholder="例如: main"
              required
            />
          </div>
        </div>

        <div class="form-group">
          <label for="remoteUrl">远程仓库地址 (URL) <span class="required">*</span></label>
          <input
            id="remoteUrl"
            v-model="form.remote_url"
            type="text"
            placeholder="git@github.com:org/repo.git 或 https://github.com/org/repo.git"
            required
          />
          <span class="input-tip">支持 git@ 或 http(s):// 开头的标准 Git 地址。</span>
        </div>

        <!-- 认证信息 -->
        <div class="section-title">认证与安全凭证</div>
        <div class="form-group">
          <label>认证方式</label>
          <div class="auth-type-cards">
            <div
              class="auth-card"
              :class="{ active: form.auth_type === 'NONE' }"
              @click="form.auth_type = 'NONE'"
            >
              <span class="icon">🔓</span>
              <span class="title">无需认证</span>
              <span class="desc">适用于公开仓库</span>
            </div>
            <div
              class="auth-card"
              :class="{ active: form.auth_type === 'SSH_KEY' }"
              @click="form.auth_type = 'SSH_KEY'"
            >
              <span class="icon">🔑</span>
              <span class="title">SSH 密钥</span>
              <span class="desc">适用于私有 SSH 仓库</span>
            </div>
            <div
              class="auth-card"
              :class="{ active: form.auth_type === 'HTTP_TOKEN' }"
              @click="form.auth_type = 'HTTP_TOKEN'"
            >
              <span class="icon">🎟️</span>
              <span class="title">HTTP Token</span>
              <span class="desc">适用于 Token/密码 凭证</span>
            </div>
          </div>
        </div>

        <!-- 凭证内容输入 (仅在需要认证时显示) -->
        <div v-if="form.auth_type !== 'NONE'" class="form-group credential-area">
          <label for="credential">
            {{ form.auth_type === "SSH_KEY" ? "SSH 私钥" : "Token / 密码" }}
            <span class="required" v-if="!hasExistingCredential">*</span>
          </label>
          <textarea
            id="credential"
            v-model="form.credential_content"
            :placeholder="
              hasExistingCredential
                ? '已配置加密凭证。若无更新无需填写此栏'
                : form.auth_type === 'SSH_KEY'
                  ? '请输入完整的 SSH 私钥 (PEM/OPENSSH 格式，含 BEGIN/END 标志)'
                  : '请输入个人访问令牌 (Personal Access Token) 或账户密码'
            "
            rows="6"
            class="code-input"
          ></textarea>
          <span class="input-tip alert" v-if="hasExistingCredential">
            💡 已配置凭证保护，若无需修改凭证本身，保留空白直接保存即可。
          </span>
        </div>

        <!-- 启用同步状态 -->
        <div class="form-group sync-toggle-group">
          <div class="toggle-label-area">
            <span class="title">开启定时同步</span>
            <span class="desc">开启后，系统将自动定时抓取该仓库并进行代码与需求分析。</span>
          </div>
          <label class="switch">
            <input type="checkbox" v-model="form.enabled" />
            <span class="slider round"></span>
          </label>
        </div>

        <!-- 仓库同步状态展示 (仅在已有配置下显示) -->
        <div v-if="existingConfig" class="sync-status-box">
          <div class="status-header">同步状态</div>
          <div class="status-grid">
            <div class="status-item">
              <span class="label">状态:</span>
              <span :class="['val', existingConfig.sync_status.toLowerCase()]">
                {{ formatSyncStatus(existingConfig.sync_status) }}
              </span>
            </div>
            <div class="status-item" v-if="existingConfig.last_synced_head_sha">
              <span class="label">最后同步 HEAD:</span>
              <span class="val sha">{{ existingConfig.last_synced_head_sha.substring(0, 8) }}</span>
            </div>
            <div class="status-item" v-if="existingConfig.last_success_at">
              <span class="label">最后成功时间:</span>
              <span class="val">{{ formatDate(existingConfig.last_success_at) }}</span>
            </div>
          </div>
          <div v-if="existingConfig.last_error_message" class="sync-error-banner">
            ❌ <b>同步错误信息:</b> {{ existingConfig.last_error_message }}
          </div>
        </div>

        <!-- 校验结果提醒 -->
        <div v-if="verifySuccess" class="alert-banner success">
          ✅ 连接验证成功！该远程代码库有效且成功检测到主干分支。
        </div>
        <div v-if="verifyError" class="alert-banner error">⚠️ 连接失败: {{ verifyError }}</div>

        <!-- 提交按钮 -->
        <div class="form-actions">
          <button
            type="button"
            class="btn secondary"
            :disabled="isTesting || isSaving"
            @click="void handleVerify()"
          >
            <span v-if="isTesting">⏳ 正在校验...</span>
            <span v-else>📡 测试连接</span>
          </button>
          <button type="submit" class="btn primary" :disabled="isTesting || isSaving">
            <span v-if="isSaving">💾 正在保存...</span>
            <span v-else>保存仓库配置</span>
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { apiClient } from "../../shared/api/client";

interface RepositoryDetail {
  id: string;
  name: string;
  remote_url: string;
  auth_type: string;
  main_branch: string;
  enabled: boolean;
  sync_status: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_synced_head_sha: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  row_version: number;
  has_credential: boolean;
}

const route = useRoute();
const projectId = route.params.projectId as string;

// 状态控制
const loading = ref(true);
const isTesting = ref(false);
const isSaving = ref(false);
const verifySuccess = ref(false);
const verifyError = ref<string | null>(null);
const hasExistingCredential = ref(false);

const existingConfig = ref<RepositoryDetail | null>(null);

// 表单对象
const form = reactive<{
  name: string;
  remote_url: string;
  auth_type: string;
  credential_content: string | null;
  main_branch: string;
  enabled: boolean;
  row_version: number | null;
}>({
  name: "",
  remote_url: "",
  auth_type: "NONE",
  credential_content: "",
  main_branch: "main",
  enabled: true,
  row_version: null,
});

async function loadConfig() {
  loading.value = true;
  verifySuccess.value = false;
  verifyError.value = null;
  try {
    const data = await apiClient.get(
      `/api/v1/projects/${projectId}/repository`,
      (val) => val as RepositoryDetail,
    );
    existingConfig.value = data;
    form.name = data.name;
    form.remote_url = data.remote_url;
    form.auth_type = data.auth_type;
    form.credential_content = ""; // 不回显凭证，留空
    form.main_branch = data.main_branch;
    form.enabled = data.enabled;
    form.row_version = data.row_version;
    hasExistingCredential.value = data.has_credential;
  } catch (e: unknown) {
    // 404 代表没有配置过仓库，属正常初始化逻辑
    const err = e as { status?: number };
    if (err.status !== 404) {
      console.error("加载仓库配置失败", e);
    }
    existingConfig.value = null;
    hasExistingCredential.value = false;
  } finally {
    loading.value = false;
  }
}

async function handleVerify() {
  if (!form.remote_url) {
    verifyError.value = "请输入远程仓库地址 (URL)";
    return;
  }

  isTesting.value = true;
  verifySuccess.value = false;
  verifyError.value = null;

  try {
    await apiClient.post(`/api/v1/projects/${projectId}/repository/verify`, (data) => data, {
      remote_url: form.remote_url,
      auth_type: form.auth_type,
      credential_content: form.credential_content || null,
      main_branch: form.main_branch,
    });
    verifySuccess.value = true;
  } catch (e: unknown) {
    const err = e as { message?: string };
    verifyError.value = err.message || "连接测试失败，请检查网络或凭证";
  } finally {
    isTesting.value = false;
  }
}

async function handleSave() {
  isSaving.value = true;
  verifySuccess.value = false;
  verifyError.value = null;

  // 整理 payload
  const payload = {
    name: form.name,
    remote_url: form.remote_url,
    auth_type: form.auth_type,
    credential_content: form.credential_content || null,
    main_branch: form.main_branch,
    enabled: form.enabled,
    row_version: form.row_version,
  };

  try {
    const res = await apiClient.post(
      `/api/v1/projects/${projectId}/repository`,
      (val) => val as RepositoryDetail,
      payload,
    );
    alert("仓库配置保存成功！");
    existingConfig.value = res;
    form.row_version = res.row_version;
    hasExistingCredential.value = res.has_credential;
    form.credential_content = ""; // 重置输入框
  } catch (e: unknown) {
    const err = e as { message?: string };
    verifyError.value = err.message || "保存仓库配置失败";
  } finally {
    isSaving.value = false;
  }
}

function formatSyncStatus(status: string) {
  const mapping: Record<string, string> = {
    NOT_SYNCED: "待首次同步",
    SYNCING: "同步分析中",
    SYNCED: "已同步",
    FAILED: "同步失败",
  };
  return mapping[status] || status;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("zh-CN");
  } catch {
    return dateStr;
  }
}

onMounted(() => {
  void loadConfig();
});
</script>

<style scoped>
.repo-settings-container {
  padding: 24px;
  color: #f1f5f9;
  max-width: 800px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
}

.page-header .subtitle {
  color: #94a3b8;
  font-size: 14px;
  margin: 0;
}

/* Glassmorphism Card */
.glass-card {
  background: rgba(30, 41, 59, 0.35);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 28px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  color: #94a3b8;
  padding: 40px;
}

.spinner {
  display: inline-block;
  animation: spin 2s linear infinite;
  margin-right: 8px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #a5b4fc;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding-bottom: 8px;
  margin: 24px 0 16px;
}

.section-title:first-of-type {
  margin-top: 0;
}

.form-row {
  display: flex;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 18px;
}

.form-group.half {
  flex: 1;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
}

.form-group label .required {
  color: #f87171;
}

.form-group input[type="text"],
.form-group textarea {
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: #f1f5f9;
  padding: 10px 14px;
  font-size: 13.5px;
  transition: all 0.3s;
}

.form-group input[type="text"]:focus,
.form-group textarea:focus {
  border-color: #6366f1;
  outline: none;
  background: rgba(15, 23, 42, 0.6);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
}

.code-input {
  font-family: monospace;
}

.input-tip {
  font-size: 12px;
  color: #64748b;
}

.input-tip.alert {
  color: #f59e0b;
}

/* Auth Cards style */
.auth-type-cards {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}

.auth-card {
  flex: 1;
  background: rgba(15, 23, 42, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  transition: all 0.3s;
}

.auth-card:hover {
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(255, 255, 255, 0.15);
}

.auth-card.active {
  background: rgba(99, 102, 241, 0.1);
  border-color: #6366f1;
  box-shadow: 0 0 10px rgba(99, 102, 241, 0.15);
}

.auth-card .icon {
  font-size: 20px;
  margin-bottom: 6px;
}

.auth-card .title {
  font-size: 13.5px;
  font-weight: 600;
  color: #cbd5e1;
}

.auth-card .desc {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
}

/* Sync Toggle */
.sync-toggle-group {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  background: rgba(15, 23, 42, 0.2);
  padding: 14px 18px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.04);
  margin-bottom: 24px;
}

.toggle-label-area {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toggle-label-area .title {
  font-size: 14px;
  font-weight: 600;
  color: #cbd5e1;
}

.toggle-label-area .desc {
  font-size: 12px;
  color: #64748b;
}

/* Switch slider */
.switch {
  position: relative;
  display: inline-block;
  width: 46px;
  height: 24px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #334155;
  transition: 0.3s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
}

input:checked + .slider {
  background-color: #6366f1;
}

input:focus + .slider {
  box-shadow: 0 0 1px #6366f1;
}

input:checked + .slider:before {
  transform: translateX(22px);
}

.slider.round {
  border-radius: 34px;
}

.slider.round:before {
  border-radius: 50%;
}

/* Sync Status Box */
.sync-status-box {
  background: rgba(15, 23, 42, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 20px;
}

.status-header {
  font-size: 13px;
  color: #94a3b8;
  font-weight: 600;
  margin-bottom: 10px;
}

.status-grid {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.status-item {
  font-size: 13px;
  display: flex;
  gap: 6px;
}

.status-item .label {
  color: #64748b;
}

.status-item .val {
  color: #cbd5e1;
  font-weight: 500;
}

.status-item .val.not_synced {
  color: #94a3b8;
}

.status-item .val.syncing {
  color: #38bdf8;
  animation: pulse 2s infinite;
}

.status-item .val.synced {
  color: #34d399;
}

.status-item .val.failed {
  color: #f87171;
}

.status-item .val.sha {
  font-family: monospace;
}

.sync-error-banner {
  margin-top: 12px;
  padding: 10px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  color: #f87171;
  font-size: 12.5px;
}

/* Alerts */
.alert-banner {
  padding: 12px 16px;
  border-radius: 6px;
  font-size: 13px;
  margin-bottom: 20px;
}

.alert-banner.success {
  background: rgba(52, 211, 153, 0.1);
  border: 1px solid rgba(52, 211, 153, 0.2);
  color: #34d399;
}

.alert-banner.error {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.2);
  color: #f87171;
}

/* Actions buttons */
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.btn {
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn.primary {
  background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%);
  color: #ffffff;
}

.btn.primary:hover {
  box-shadow: 0 0 12px rgba(99, 102, 241, 0.4);
}

.btn.secondary {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
}

.btn.secondary:hover {
  background: rgba(255, 255, 255, 0.1);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  box-shadow: none;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}
</style>
