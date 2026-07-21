import { defineStore } from "pinia";
import { ref } from "vue";
import { apiClient } from "../api/client";

export interface ProjectDetail {
  id: string;
  key: string;
  name: string;
  description: string;
  status: "active" | "archived";
  created_at: string;
}

export interface ProjectContext {
  project_id: string;
  role_id: string | null;
  permissions: string[];
}

export function decodeProjectDetail(value: unknown): ProjectDetail {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid project detail");
  }
  const o = value as Record<string, unknown>;
  return {
    id: typeof o.id === "string" ? o.id : "",
    key: typeof o.key === "string" ? o.key : "",
    name: typeof o.name === "string" ? o.name : "",
    description: typeof o.description === "string" ? o.description : "",
    status: o.status === "archived" ? "archived" : "active",
    created_at: typeof o.created_at === "string" ? o.created_at : "",
  };
}

export function decodeProjectContext(value: unknown): ProjectContext {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid project context");
  }
  const o = value as Record<string, unknown>;
  return {
    project_id: typeof o.project_id === "string" ? o.project_id : "",
    role_id: typeof o.role_id === "string" ? o.role_id : null,
    permissions: Array.isArray(o.permissions) ? o.permissions.map(String) : [],
  };
}

export const useProjectStore = defineStore("project", () => {
  const currentProjectId = ref<string | null>(null);
  const currentProject = ref<ProjectDetail | null>(null);
  const memberRole = ref<string | null>(null);
  const permissions = ref<string[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function loadProjectContext(projectId: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      // 加载项目上下文 (包含当前用户在该项目内的角色及权限)
      const ctx = await apiClient.get(
        `/api/v1/projects/${projectId}/context`,
        decodeProjectContext,
      );
      // 加载项目本身的基本信息
      const proj = await apiClient.get(`/api/v1/projects/${projectId}`, decodeProjectDetail);

      currentProjectId.value = projectId;
      currentProject.value = proj;
      memberRole.value = ctx.role_id;
      permissions.value = ctx.permissions;
    } catch (e: unknown) {
      reset();
      error.value = e instanceof Error ? e.message : "加载项目上下文失败";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  function reset(): void {
    currentProjectId.value = null;
    currentProject.value = null;
    memberRole.value = null;
    permissions.value = [];
    error.value = null;
  }

  function hasPermission(permission: string): boolean {
    return permissions.value.includes(permission);
  }

  return {
    currentProjectId,
    currentProject,
    memberRole,
    permissions,
    loading,
    error,
    loadProjectContext,
    reset,
    hasPermission,
  };
});
