import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "./auth";
import { useProjectStore } from "./project";
import { apiClient } from "../api/client";

describe("Stores Test Suite", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("authStore - restores session successfully", async () => {
    const mockUser = {
      id: "user-123",
      username: "testuser",
      email: "test@tw.com",
      display_name: "Test User",
      is_system_admin: false,
      status: "active",
    };

    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValue(mockUser);
    const authStore = useAuthStore();

    const user = await authStore.restoreSession();

    expect(getSpy).toHaveBeenCalledWith("/api/v1/auth/me", expect.any(Function));
    expect(authStore.currentUser).toEqual(mockUser);
    expect(authStore.isInitialized).toBe(true);
    expect(user).toEqual(mockUser);
  });

  it("authStore - handle restore session failure", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("Unauthorized"));
    const authStore = useAuthStore();

    const user = await authStore.restoreSession();

    expect(authStore.currentUser).toBeNull();
    expect(authStore.isInitialized).toBe(true);
    expect(user).toBeNull();
  });

  it("projectStore - resets project state correctly", () => {
    const projectStore = useProjectStore();
    projectStore.currentProjectId = "proj-123";
    projectStore.permissions = ["read", "write"];

    projectStore.reset();

    expect(projectStore.currentProjectId).toBeNull();
    expect(projectStore.permissions).toEqual([]);
  });

  it("projectStore - load project context successfully", async () => {
    const mockContext = {
      project_id: "proj-123",
      role_id: "project_admin",
      permissions: ["project.member.manage", "project.update"],
    };
    const mockProjectDetail = {
      id: "proj-123",
      key: "PROJA",
      name: "Project A",
      description: "Desc",
      status: "active",
      created_at: "2026-07-20T00:00:00Z",
    };

    const getSpy = vi.spyOn(apiClient, "get").mockImplementation((path) => {
      if (path.includes("/context")) {
        return Promise.resolve(mockContext);
      }
      return Promise.resolve(mockProjectDetail);
    });

    const projectStore = useProjectStore();
    await projectStore.loadProjectContext("proj-123");

    expect(getSpy).toHaveBeenCalledTimes(2);
    expect(projectStore.currentProjectId).toBe("proj-123");
    expect(projectStore.currentProject).toEqual(mockProjectDetail);
    expect(projectStore.memberRole).toBe("project_admin");
    expect(projectStore.hasPermission("project.member.manage")).toBe(true);
    expect(projectStore.hasPermission("project.delete")).toBe(false);
  });
});
