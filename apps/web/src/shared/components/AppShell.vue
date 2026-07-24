<template>
  <div class="app-layout">
    <!-- 归档只读全局提示栏 -->
    <div v-if="projectStore.currentProject?.status === 'archived'" class="archived-banner">
      <span class="banner-icon">⚠️</span>
      <span>项目已归档 (只读) - 所有写入操作已被禁用。</span>
    </div>

    <div class="main-shell">
      <!-- 左侧边栏侧栏 -->
      <aside class="sidebar">
        <!-- 侧栏头部 -->
        <div class="sidebar-header" @click="goProjectsList">
          <div class="logo-box">⚡</div>
          <span class="brand-name">TestWeave</span>
        </div>

        <!-- 项目上下文切换器 -->
        <div class="project-switcher">
          <div class="switcher-trigger" @click="showProjDropdown = !showProjDropdown">
            <div class="active-proj-info">
              <span class="proj-name">{{ projectStore.currentProject?.name || "加载中..." }}</span>
              <span class="proj-key">{{ projectStore.currentProject?.key || "..." }}</span>
            </div>
            <span class="arrow-icon" :class="{ open: showProjDropdown }">▼</span>
          </div>

          <div v-if="showProjDropdown" v-click-outside="closeDropdown" class="dropdown-list">
            <div class="dropdown-header">切换项目</div>
            <div
              v-for="p in projectsList"
              :key="p.id"
              class="dropdown-item"
              :class="{ active: p.id === projectStore.currentProjectId }"
              @click="switchProject(p.id)"
            >
              <div class="item-info">
                <span class="item-name">{{ p.name }}</span>
                <span class="item-key">{{ p.key }}</span>
              </div>
              <span v-if="p.id === projectStore.currentProjectId" class="active-check">✓</span>
            </div>
            <div class="dropdown-footer" @click="goProjectsList">📂 查看所有项目</div>
          </div>
        </div>

        <!-- 一级导航菜单 -->
        <nav class="nav-menu">
          <div
            v-for="item in visibleMenuItems"
            :key="item.path"
            class="nav-item"
            :class="{ active: isMenuItemActive(item.path) }"
            @click="navigateMenu(item.path)"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span class="nav-label">{{ item.label }}</span>
          </div>
        </nav>
      </aside>

      <!-- 右侧主体内容 -->
      <div class="main-container">
        <!-- 顶部导航栏 -->
        <header class="topbar">
          <div class="breadcrumb">
            <span class="bc-root">项目列表</span>
            <span class="bc-sep">/</span>
            <span class="bc-active">{{ projectStore.currentProject?.name }}</span>
            <span class="bc-sep">/</span>
            <span class="bc-active page-title">{{ currentPageTitle }}</span>
          </div>

          <div class="user-action">
            <span class="user-display">{{ authStore.currentUser?.display_name }}</span>
            <button class="logout-btn" @click="handleLogout">退出登录</button>
          </div>
        </header>

        <!-- 主路由渲染区 -->
        <main class="content-area">
          <router-view></router-view>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { useProjectStore } from "../stores/project";
import { apiClient } from "../api/client";

interface ProjectItem {
  id: string;
  key: string;
  name: string;
}

const authStore = useAuthStore();
const projectStore = useProjectStore();
const router = useRouter();
const route = useRoute();

const showProjDropdown = ref(false);
const projectsList = ref<ProjectItem[]>([]);

// 8个固定顺序的一级导航菜单定义
const menuItems = [
  { path: "/workbench", label: "工作台", icon: "📊" },
  { path: "/versions", label: "版本", icon: "🏷️" },
  { path: "/tasks", label: "测试任务", icon: "📋" },
  { path: "/cases", label: "用例库", icon: "🗂️" },
  { path: "/defects", label: "缺陷", icon: "🐛" },
  { path: "/reports", label: "报告", icon: "📈" },
  { path: "/agent", label: "AI 能力中心", icon: "🤖", requirePermission: "agent.use" },
  { path: "/repository-settings", label: "仓库配置", icon: "📦", requireAdmin: true },
  { path: "/admin", label: "管理员设置", icon: "⚙️", requireAdmin: true },
];

const visibleMenuItems = computed(() => {
  return menuItems.filter((item) => {
    if (authStore.currentUser?.is_system_admin) return true;
    if (item.requireAdmin) {
      return projectStore.memberRole === "project_admin";
    }
    if (item.requirePermission) {
      return projectStore.hasPermission(item.requirePermission);
    }
    return true;
  });
});

const currentPageTitle = computed(() => {
  const currentPath = route.path;
  const match = menuItems.find((item) => currentPath.endsWith(item.path));
  return match ? match.label : "概览";
});

function decodeProjects(value: unknown): ProjectItem[] {
  if (Array.isArray(value)) {
    return value.map((o: unknown) => {
      const item = o as Record<string, unknown>;
      return {
        id: String((item.id as string) ?? ""),
        key: String((item.key as string) ?? ""),
        name: String((item.name as string) ?? ""),
      };
    });
  }
  return [];
}

async function loadDropdownProjects(): Promise<void> {
  try {
    const list = await apiClient.get("/api/v1/projects", decodeProjects);
    projectsList.value = list;
  } catch {
    // 降级不阻塞
  }
}

function closeDropdown(): void {
  showProjDropdown.value = false;
}

async function goProjectsList(): Promise<void> {
  await router.push("/projects");
}

async function switchProject(projectId: string): Promise<void> {
  closeDropdown();
  if (projectId === projectStore.currentProjectId) return;

  // 进行项目切换，路由会触发项目上下文重新加载
  const currentSubPath =
    menuItems.find((item) => route.path.endsWith(item.path))?.path ?? "/workbench";
  await router.push(`/projects/${projectId}${currentSubPath}`);
}

async function handleLogout(): Promise<void> {
  await authStore.logout();
  projectStore.reset();
  await router.push("/login");
}

function isMenuItemActive(menuPath: string): boolean {
  const currentPath = route.path;
  const projectPrefix = `/projects/${projectStore.currentProjectId}`;

  if (menuPath === "/tasks") {
    return (
      currentPath.startsWith(`${projectPrefix}/test-tasks`) ||
      currentPath.startsWith(`${projectPrefix}/tasks`)
    );
  }
  return currentPath.startsWith(`${projectPrefix}${menuPath}`);
}

async function navigateMenu(menuPath: string): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (menuPath === "/versions") {
    const userId = authStore.currentUser?.id;
    const lastVersionId = localStorage.getItem(`last_version:${userId}:${projectId}`);
    if (lastVersionId) {
      await router.push(`/projects/${projectId}/versions/${lastVersionId}`);
      return;
    }
  }

  if (menuPath === "/tasks") {
    await router.push(`/projects/${projectId}/test-tasks`);
    return;
  }

  await router.push(`/projects/${projectId}${menuPath}`);
}

type ClickOutsideElement = HTMLElement & { clickOutsideEvent?: (event: Event) => void };

// 模拟 v-click-outside 指令，以便点击下拉框外部时自动收回
const vClickOutside = {
  mounted(el: ClickOutsideElement, binding: { value: () => void }) {
    el.clickOutsideEvent = (event: Event) => {
      if (!(el === event.target || el.contains(event.target as Node))) {
        binding.value();
      }
    };
    document.addEventListener("click", el.clickOutsideEvent);
  },
  unmounted(el: ClickOutsideElement) {
    if (el.clickOutsideEvent) {
      document.removeEventListener("click", el.clickOutsideEvent);
    }
  },
};

onMounted(() => {
  // eslint-disable-next-line @typescript-eslint/no-floating-promises
  loadDropdownProjects();
});
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: #0b0f19;
  color: #cbd5e1;
  font-family:
    "Inter",
    system-ui,
    -apple-system,
    sans-serif;
  overflow: hidden;
}

.archived-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: linear-gradient(90deg, #d97706, #b45309);
  color: #ffffff;
  padding: 8px;
  font-size: 13px;
  font-weight: 600;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.banner-icon {
  font-size: 14px;
}

.main-shell {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.sidebar {
  width: 260px;
  background-color: #0f172a;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.02);
}

.logo-box {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #ffffff;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
}

.brand-name {
  color: #f1f5f9;
  font-size: 18px;
  font-weight: 800;
}

.project-switcher {
  position: relative;
  margin: 16px 20px;
}

.switcher-trigger {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.switcher-trigger:hover {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(99, 102, 241, 0.3);
}

.active-proj-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.proj-name {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 600;
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proj-key {
  color: #64748b;
  font-size: 10px;
  font-family: monospace;
}

.arrow-icon {
  font-size: 10px;
  color: #64748b;
  transition: transform 0.2s ease;
}

.arrow-icon.open {
  transform: rotate(180deg);
}

.dropdown-list {
  position: absolute;
  top: 100%;
  left: 0;
  width: 100%;
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  margin-top: 8px;
  z-index: 500;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
}

.dropdown-header {
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  padding: 10px 14px 6px 14px;
}

.dropdown-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dropdown-item:hover {
  background: rgba(99, 102, 241, 0.08);
}

.dropdown-item.active {
  background: rgba(99, 102, 241, 0.15);
}

.item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.item-name {
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 500;
}

.item-key {
  color: #475569;
  font-size: 9px;
  font-family: monospace;
}

.active-check {
  color: #818cf8;
  font-size: 12px;
  font-weight: bold;
}

.dropdown-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  padding: 12px;
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
  cursor: pointer;
}

.dropdown-footer:hover {
  color: #818cf8;
}

.nav-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.02);
  color: #e2e8f0;
}

.nav-item.active {
  background: rgba(99, 102, 241, 0.1);
  color: #a5b4fc;
  font-weight: 600;
  box-shadow: inset 3px 0 0 #6366f1;
}

.main-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar {
  height: 64px;
  background-color: #0f172a;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 40px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}

.bc-sep {
  color: #334155;
}

.bc-active {
  color: #94a3b8;
}

.page-title {
  color: #cbd5e1;
  font-weight: 600;
}

.user-action {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-display {
  color: #94a3b8;
  font-size: 13px;
}

.logout-btn {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #64748b;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.logout-btn:hover {
  border-color: #f87171;
  color: #f87171;
}

.content-area {
  flex: 1;
  padding: 40px;
  overflow-y: auto;
  box-sizing: border-box;
}
</style>
