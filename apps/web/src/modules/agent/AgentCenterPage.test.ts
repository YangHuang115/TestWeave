import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentCenterPage from "./AgentCenterPage.vue";

const { push, get } = vi.hoisted(() => ({ push: vi.fn(), get: vi.fn() }));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { projectId: "proj-123" } }),
  useRouter: () => ({ push }),
}));

vi.mock("../../shared/api/client", () => ({
  apiClient: { get },
}));

describe("AgentCenterPage.vue", () => {
  beforeEach(() => {
    push.mockReset();
    get.mockReset();
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/auth/me") return Promise.resolve({ is_system_admin: false });
      if (path.endsWith("/external-tokens")) return Promise.resolve({ tokens: [] });
      return Promise.resolve([]);
    });
  });

  it("renders AI capability center title and subtitle correctly", () => {
    const wrapper = mount(AgentCenterPage, {
      global: {
        stubs: ["router-link", "router-view"],
      },
    });

    expect(wrapper.find(".title").text()).toBe("AI 能力中心");
    expect(wrapper.find(".subtitle").text()).toBe(
      "管理平台可同步、只读查看的 AI 测试能力、拓扑流水线以及外部智能体。",
    );
  });

  it("provides a visible device monitor entry for the current project", async () => {
    const wrapper = mount(AgentCenterPage);

    const entry = wrapper.get("button.device-monitor-entry");
    expect(entry.text()).toContain("设备监看");
    expect(entry.text()).toContain("实时查看 Agent 操作结果");

    await entry.trigger("click");

    expect(push).toHaveBeenCalledOnce();
    expect(push).toHaveBeenCalledWith("/projects/proj-123/agent/devices");
  });
});
