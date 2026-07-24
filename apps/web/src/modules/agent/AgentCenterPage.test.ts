import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import AgentCenterPage from "./AgentCenterPage.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { projectId: "proj-123" } }),
  useRouter: () => ({ push: vi.fn() }),
}));

describe("AgentCenterPage.vue", () => {
  it("renders AI capability center title and subtitle correctly", () => {
    const wrapper = mount(AgentCenterPage, {
      global: {
        stubs: ["router-link", "router-view"],
      },
    });

    expect(wrapper.find(".title").text()).toBe("AI 能力中心");
    expect(wrapper.find(".subtitle").text()).toBe("管理平台可同步、只读查看的 AI 测试能力、拓扑流水线以及外部智能体。");
  });
});
