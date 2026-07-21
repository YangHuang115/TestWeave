<template>
  <div class="login-wrapper">
    <!-- 星空科技感背景背景 -->
    <div class="glow-bg"></div>

    <div class="login-container">
      <!-- 品牌故事 -->
      <div class="brand-side">
        <h1 class="logo">TestWeave</h1>
        <p class="slogan">用 AI 原生智能加速软件测试。</p>
        <div class="features-list">
          <div class="feature-item">
            <span class="feature-icon">⚡</span>
            <div>
              <h4>高效</h4>
              <p>即时生成与审查测试场景。</p>
            </div>
          </div>
          <div class="feature-item">
            <span class="feature-icon">🛡️</span>
            <div>
              <h4>可靠</h4>
              <p>强大的安全防护与严苛的沙箱隔离运行。</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 登录表单 -->
      <div class="form-side">
        <div class="glass-card">
          <h2>欢迎回来</h2>
          <p class="subtitle">登录您的账号以访问工作区</p>

          <form @submit.prevent="handleSubmit">
            <!-- 账号 -->
            <div class="form-group">
              <label for="identity">用户名或邮箱</label>
              <input
                id="identity"
                v-model="form.usernameOrEmail"
                type="text"
                required
                placeholder="请输入用户名或邮箱"
                :disabled="isLoading"
              />
            </div>

            <!-- 密码 -->
            <div class="form-group">
              <label for="password">密码</label>
              <div class="password-input-wrapper">
                <input
                  id="password"
                  v-model="form.password"
                  :type="showPassword ? 'text' : 'password'"
                  required
                  placeholder="请输入密码"
                  :disabled="isLoading"
                />
                <button type="button" class="toggle-pwd-btn" @click="showPassword = !showPassword">
                  {{ showPassword ? "🙈" : "👁️" }}
                </button>
              </div>
            </div>

            <!-- 错误提示 -->
            <div v-if="errorMsg" class="error-banner">
              <span class="err-icon">⚠️</span>
              <span class="err-text">{{ errorMsg }}</span>
            </div>

            <!-- 登录按钮 -->
            <button type="submit" class="submit-btn" :disabled="isLoading">
              <span v-if="isLoading" class="loader"></span>
              <span v-else>登录</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../../shared/stores/auth";
import { apiClient } from "../../shared/api/client";

interface ProjectItem {
  id: string;
}

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const form = reactive({
  usernameOrEmail: "",
  password: "",
});

const showPassword = ref(false);
const isLoading = ref(false);
const errorMsg = ref<string | null>(null);

function decodeProjects(value: unknown): ProjectItem[] {
  if (Array.isArray(value)) {
    return value.map((o: unknown) => {
      const item = o as Record<string, unknown>;
      return { id: String((item.id as string) ?? "") };
    });
  }
  return [];
}

async function handleSubmit(): Promise<void> {
  if (isLoading.value) return;
  isLoading.value = true;
  errorMsg.value = null;

  try {
    await authStore.login(form.usernameOrEmail, form.password);

    // 登录成功，决定下一步跳转
    // 优先跳转 returnUrl (必须以 / 开头，防外链钓鱼)
    const returnUrl = route.query.returnUrl;
    if (typeof returnUrl === "string" && returnUrl.startsWith("/")) {
      await router.push(returnUrl);
      return;
    }

    // 没有 returnUrl，则查询该用户所属项目列表以自动引导
    try {
      const projects = await apiClient.get("/api/v1/projects", decodeProjects);
      if (projects.length === 1 && projects[0]) {
        // 只有一个项目，直接进入该项目工作台
        await router.push(`/projects/${projects[0].id}/workbench`);
      } else {
        // 多个或无项目进入项目选择列表
        await router.push("/projects");
      }
    } catch {
      await router.push("/projects");
    }
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : "登录失败，请检查账号密码";
  } finally {
    isLoading.value = false;
  }
}
</script>

<style scoped>
.login-wrapper {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #0b0f19;
  overflow: hidden;
  font-family:
    "Inter",
    system-ui,
    -apple-system,
    sans-serif;
}

.glow-bg {
  position: absolute;
  top: -10%;
  left: -10%;
  width: 50%;
  height: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, rgba(0, 0, 0, 0) 70%);
  z-index: 1;
}

.login-container {
  display: flex;
  width: 100%;
  max-width: 1000px;
  height: 600px;
  z-index: 10;
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.brand-side {
  flex: 1;
  background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
  padding: 60px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}

.logo {
  font-size: 32px;
  font-weight: 800;
  background: linear-gradient(135deg, #a5b4fc 0%, #818cf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 16px;
}

.slogan {
  color: #94a3b8;
  font-size: 16px;
  line-height: 1.6;
  margin-bottom: 48px;
}

.features-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.feature-item {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.feature-icon {
  font-size: 24px;
  filter: drop-shadow(0 0 8px rgba(99, 102, 241, 0.5));
}

.feature-item h4 {
  color: #f1f5f9;
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
}

.feature-item p {
  color: #64748b;
  font-size: 13px;
  line-height: 1.4;
}

.form-side {
  flex: 1.1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.glass-card {
  width: 100%;
  max-width: 380px;
}

h2 {
  color: #f1f5f9;
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
}

.subtitle {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 32px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.form-group label {
  color: #94a3b8;
  font-size: 13px;
  font-weight: 500;
}

.form-group input {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 12px 16px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
  transition: all 0.2s ease;
}

.form-group input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.password-input-wrapper {
  position: relative;
  display: flex;
}

.password-input-wrapper input {
  width: 100%;
  padding-right: 48px;
}

.toggle-pwd-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 16px;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 24px;
}

.err-icon {
  font-size: 16px;
}

.err-text {
  color: #f87171;
  font-size: 13px;
}

.submit-btn {
  width: 100%;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 14px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.submit-btn:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.loader {
  width: 18px;
  height: 18px;
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
