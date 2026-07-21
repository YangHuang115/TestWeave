<template>
  <div class="error-container">
    <div class="error-card">
      <div class="error-code">{{ code }}</div>
      <h2>{{ title }}</h2>
      <p class="desc">{{ message }}</p>
      <button class="home-btn" @click="goHome">返回安全区域</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

const code = computed(() => {
  if (route.path.includes("403")) return "403";
  return "404";
});

const title = computed(() => {
  return code.value === "403" ? "无访问权限" : "页面未找到";
});

const message = computed(() => {
  return code.value === "403"
    ? "您不具备该资源或项目工作空间的访问权限。如有疑问请联系系统管理员。"
    : "您正在寻找的页面或项目工作空间不存在、已被删除，或您没有权限查看它。";
});

async function goHome(): Promise<void> {
  await router.push("/projects");
}
</script>

<style scoped>
.error-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background-color: #0b0f19;
  font-family:
    "Inter",
    system-ui,
    -apple-system,
    sans-serif;
  padding: 20px;
}

.error-card {
  background: rgba(30, 41, 59, 0.4);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 50px 40px;
  text-align: center;
  max-width: 480px;
  width: 100%;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.error-code {
  font-size: 80px;
  font-weight: 900;
  background: linear-gradient(135deg, #f43f5e 0%, #ec4899 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1;
  margin-bottom: 20px;
  filter: drop-shadow(0 0 15px rgba(244, 63, 94, 0.3));
}

h2 {
  color: #f1f5f9;
  font-size: 24px;
  margin-bottom: 12px;
  font-weight: 700;
}

.desc {
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 32px;
}

.home-btn {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 12px 28px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
  transition: all 0.2s ease;
}

.home-btn:hover {
  opacity: 0.95;
  transform: translateY(-1px);
}
</style>
