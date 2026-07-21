import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../shared/stores/auth";
import { useProjectStore } from "../shared/stores/project";

// 引入模块页面
import LoginPage from "../modules/auth/LoginPage.vue";
import ProjectListPage from "../modules/projects/ProjectListPage.vue";
import AppShell from "../shared/components/AppShell.vue";
import WorkbenchPage from "../modules/workbench/WorkbenchPage.vue";
import VersionsPage from "../modules/versions/VersionsPage.vue";
import VersionDetailPage from "../modules/versions/VersionDetailPage.vue";
import RequirementDetailPage from "../modules/requirements/RequirementDetailPage.vue";
import TasksPage from "../modules/tasks/TasksPage.vue";
import TaskDetailPage from "../modules/tasks/TaskDetailPage.vue";
import CasesPage from "../modules/cases/CasesPage.vue";
import MindmapPage from "../modules/cases/MindmapPage.vue";
import DefectsPage from "../modules/defects/DefectsPage.vue";
import ReportsPage from "../modules/reports/ReportsPage.vue";
import AgentCenterPage from "../modules/agent/AgentCenterPage.vue";
import AdminSettingsPage from "../modules/admin/AdminSettingsPage.vue";
import RepositorySettingsPage from "../modules/repository-settings/RepositorySettingsPage.vue";
import ErrorPage from "../modules/foundation/ErrorPage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: LoginPage,
    },
    {
      path: "/projects",
      name: "projects",
      component: ProjectListPage,
    },
    {
      path: "/projects/:projectId",
      component: AppShell,
      children: [
        { path: "", redirect: (to) => `${to.path}/workbench` },
        { path: "workbench", component: WorkbenchPage },
        { path: "versions", component: VersionsPage },
        { path: "versions/:versionId", component: VersionDetailPage },
        {
          path: "versions/:versionId/requirements/:requirementId",
          component: RequirementDetailPage,
        },
        { path: "tasks", redirect: (to) => `/projects/${to.params.projectId}/test-tasks` },
        { path: "test-tasks", component: TasksPage },
        { path: "test-tasks/:taskId", component: TaskDetailPage },
        { path: "test-tasks/:taskId/mindmap", component: MindmapPage },
        { path: "cases", component: CasesPage },
        { path: "defects", component: DefectsPage },
        { path: "reports", component: ReportsPage },
        { path: "agent", component: AgentCenterPage },
        { path: "repository-settings", component: RepositorySettingsPage },
        { path: "admin", component: AdminSettingsPage },
      ],
    },
    {
      path: "/403",
      name: "forbidden",
      component: ErrorPage,
    },
    {
      path: "/404",
      name: "notFound",
      component: ErrorPage,
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/404",
    },
  ],
});

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore();
  const projectStore = useProjectStore();

  // 1. 初始化会话恢复
  if (!authStore.isInitialized) {
    await authStore.restoreSession();
  }

  const isAuthenticated = !!authStore.currentUser;

  // 2. 如果目标路由是登录页，但用户已登录，重定向回项目列表
  if (to.path === "/login") {
    if (isAuthenticated) {
      next("/projects");
    } else {
      next();
    }
    return;
  }

  // 3. 全局登录拦截
  if (!isAuthenticated) {
    // 强制跳转到登录，并带上原本要去的目标路径供登录后跳回
    next({
      path: "/login",
      query: { returnUrl: to.fullPath },
    });
    return;
  }

  // 4. 项目级路由上下文校验与加载
  const projectId = to.params.projectId;
  if (projectId && typeof projectId === "string") {
    // 如果跳转的新项目 ID 与当前 Store 中已加载的不一致，需要拉取上下文
    if (projectStore.currentProjectId !== projectId) {
      try {
        await projectStore.loadProjectContext(projectId);
      } catch {
        // 项目不存在、无权或接口异常时，直接跳转至 404
        next("/404");
        return;
      }
    }

    // 5. 校验管理员与仓库配置页权限
    if (to.path.endsWith("/admin") || to.path.endsWith("/repository-settings")) {
      const isProjectAdmin = projectStore.memberRole === "project_admin";
      const isSystemAdmin = authStore.currentUser?.is_system_admin;
      if (!isProjectAdmin && !isSystemAdmin) {
        next("/403");
        return;
      }
    }
  }

  next();
});
