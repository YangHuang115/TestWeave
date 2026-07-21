import { defineStore } from "pinia";
import { ref } from "vue";
import { apiClient } from "../api/client";

export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string;
  is_system_admin: boolean;
  status: "active" | "inactive";
}

export function decodeUser(value: unknown): User {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid user object");
  }
  const o = value as Record<string, unknown>;
  return {
    id: typeof o.id === "string" ? o.id : "",
    username: typeof o.username === "string" ? o.username : "",
    email: typeof o.email === "string" ? o.email : "",
    display_name: typeof o.display_name === "string" ? o.display_name : "",
    is_system_admin: Boolean(o.is_system_admin),
    status: o.status === "inactive" ? "inactive" : "active",
  };
}

function decodeStatus(value: unknown): { status: string } {
  if (typeof value === "object" && value !== null && "status" in value) {
    const o = value as Record<string, unknown>;
    return { status: typeof o.status === "string" ? o.status : "ok" };
  }
  return { status: "ok" };
}

export const useAuthStore = defineStore("auth", () => {
  const currentUser = ref<User | null>(null);
  const isInitialized = ref(false);
  const isAuthenticating = ref(false);

  async function login(usernameOrEmail: string, password: string): Promise<User> {
    isAuthenticating.value = true;
    try {
      const user = await apiClient.post("/api/v1/auth/login", decodeUser, {
        username_or_email: usernameOrEmail,
        password,
      });
      currentUser.value = user;
      return user;
    } finally {
      isAuthenticating.value = false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await apiClient.post("/api/v1/auth/logout", decodeStatus);
    } catch {
      // 即使后端退出请求失败，前端也强制清理会话
    } finally {
      currentUser.value = null;
    }
  }

  async function restoreSession(): Promise<User | null> {
    try {
      const user = await apiClient.get("/api/v1/auth/me", decodeUser);
      currentUser.value = user;
      return user;
    } catch {
      currentUser.value = null;
      return null;
    } finally {
      isInitialized.value = true;
    }
  }

  function clearSession(): void {
    currentUser.value = null;
  }

  return {
    currentUser,
    isInitialized,
    isAuthenticating,
    login,
    logout,
    restoreSession,
    clearSession,
  };
});
