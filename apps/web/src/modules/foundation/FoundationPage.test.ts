import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/client";
import { getReadyHealth } from "../../shared/api/health";
import FoundationPage from "./FoundationPage.vue";

vi.mock("../../shared/api/health", () => ({
  getReadyHealth: vi.fn(),
}));

const mockedGetReadyHealth = vi.mocked(getReadyHealth);

describe("FoundationPage", () => {
  it("shows real loading state and then the connected state", async () => {
    let resolveHealth:
      ((value: { status: "ok"; checks: { database: "ok"; migrations: "ok" } }) => void) | undefined;
    mockedGetReadyHealth.mockReturnValue(
      new Promise((resolve) => {
        resolveHealth = resolve;
      }),
    );

    const wrapper = mount(FoundationPage);
    expect(wrapper.get('[role="status"]').text()).toContain("正在连接服务端");

    resolveHealth?.({
      status: "ok",
      checks: { database: "ok", migrations: "ok" },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("服务端连接正常");
    expect(wrapper.text()).toContain("数据库与迁移状态正常");
    expect(wrapper.text()).not.toContain("示例数据");
  });

  it("shows the public error and request id when the health call fails", async () => {
    mockedGetReadyHealth.mockRejectedValue(
      new ApiError({
        code: "SERVICE_NOT_READY",
        message: "服务暂未就绪，请稍后重试",
        requestId: "req_visible_789",
        retryable: true,
        details: null,
        status: 503,
      }),
    );

    const wrapper = mount(FoundationPage);
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("服务暂未就绪，请稍后重试");
    expect(wrapper.text()).toContain("req_visible_789");
  });
});
