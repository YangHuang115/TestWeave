import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import AndroidDeviceMonitorPage from "./AndroidDeviceMonitorPage.vue";

const { list, getScreen, createStream, createObjectUrl, revokeObjectUrl } = vi.hoisted(() => ({
  list: vi.fn(),
  getScreen: vi.fn(),
  createStream: vi.fn(),
  createObjectUrl: vi.fn(() => "blob:android-screen"),
  revokeObjectUrl: vi.fn(),
}));

vi.mock("./androidDevicesApi", () => ({
  androidDevicesApi: { list, getScreen },
  isAndroidRequestCancelled: (error: unknown) =>
    error instanceof ApiError && error.code === "REQUEST_CANCELLED",
}));

vi.mock("./androidDeviceStream", () => ({
  createAndroidDeviceStream: createStream,
}));

interface MockStreamStatus {
  state: string;
  attempt: number;
  effectiveFps: number | null;
}

interface MockStreamFailure {
  code: string;
  message: string;
  retryable: boolean;
  closeCode: number | null;
}

interface MockStreamOptions {
  projectId: string;
  deviceRef: string;
  onStatus: (status: MockStreamStatus) => void;
  onFrame: (frame: {
    blob: Blob;
    capturedAt: string;
    sequence: number;
    effectiveFps: number | null;
  }) => void;
  onFailure: (failure: MockStreamFailure) => void;
}

interface MockStreamController {
  start: ReturnType<typeof vi.fn>;
  pause: ReturnType<typeof vi.fn>;
  resume: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

const streamControllers: MockStreamController[] = [];

const devices = [
  {
    deviceRef: "v1_online",
    displayName: "Pixel 8",
    state: "online",
    model: "Pixel 8",
    infoAvailable: true,
    infoError: null,
  },
  {
    deviceRef: "v1_offline",
    displayName: "Galaxy S23",
    state: "offline",
    model: "Galaxy S23",
    infoAvailable: false,
    infoError: "设备当前不可用",
  },
];

function pngResponse() {
  return { blob: new Blob(["png"], { type: "image/png" }), capturedAt: "2026-07-28T03:00:00Z" };
}

describe("AndroidDeviceMonitorPage.vue", () => {
  beforeEach(() => {
    list.mockReset();
    getScreen.mockReset();
    createStream.mockReset();
    createObjectUrl.mockClear();
    revokeObjectUrl.mockClear();
    streamControllers.length = 0;
    list.mockResolvedValue({ items: devices, total: devices.length });
    getScreen.mockResolvedValue(pngResponse());
    createStream.mockImplementation((options: MockStreamOptions) => {
      const controller: MockStreamController = {
        start: vi.fn(() =>
          options.onStatus({ state: "connecting", attempt: 0, effectiveFps: null }),
        ),
        pause: vi.fn(() => options.onStatus({ state: "paused", attempt: 0, effectiveFps: null })),
        resume: vi.fn(() =>
          options.onStatus({ state: "connecting", attempt: 0, effectiveFps: null }),
        ),
        stop: vi.fn(),
      };
      streamControllers.push(controller);
      return controller;
    });
    vi.stubGlobal("URL", {
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    });
  });

  it("loads the shared device list and captures exactly one initial online frame", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project one" } });
    await flushPromises();

    expect(list).toHaveBeenCalledOnce();
    expect(list).toHaveBeenCalledWith("project one", expect.any(AbortSignal));
    expect(getScreen).toHaveBeenCalledOnce();
    expect(getScreen).toHaveBeenCalledWith("project one", "v1_online", expect.any(AbortSignal));
    expect(createStream).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: "project one", deviceRef: "v1_online" }),
    );
    expect(streamControllers[0]?.start).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("Pixel 8");
    expect(wrapper.text()).toContain("最后成功画面");
    wrapper.unmount();
  });

  it("does not capture an offline device when it is selected", async () => {
    list.mockResolvedValue({
      items: [devices[1], { ...devices[0], deviceRef: "v1_online_2", displayName: "Pixel 7" }],
      total: 2,
    });
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();
    expect(getScreen).toHaveBeenCalledOnce();
    expect(getScreen.mock.calls[0]?.[1]).toBe("v1_online_2");

    await wrapper.findAll("button.device-item")[0]!.trigger("click");
    await flushPromises();
    expect(getScreen).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("keeps the last successful frame visible when a manual refresh fails", async () => {
    getScreen.mockResolvedValueOnce(pngResponse()).mockRejectedValueOnce(
      new ApiError({
        code: "ANDROID_MCP_TIMEOUT",
        message: "Android MCP 响应超时",
        requestId: "req_screen_timeout",
        retryable: true,
        details: null,
        status: 504,
      }),
    );
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();
    await wrapper.get("button.single-frame-button").trigger("click");
    await flushPromises();

    expect(wrapper.find("img").exists()).toBe(true);
    expect(wrapper.text()).toContain("最后成功画面仍保留");
    expect(wrapper.text()).toContain("req_screen_timeout");
    wrapper.unmount();
  });

  it("renders an MCP unavailable error with a retry action", async () => {
    list.mockRejectedValue(
      new ApiError({
        code: "ANDROID_MCP_UNAVAILABLE",
        message: "Android MCP 运行时不可用",
        requestId: "req_device_list",
        retryable: true,
        details: null,
        status: 503,
      }),
    );
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    expect(wrapper.text()).toContain("Android MCP 运行时不可用");
    expect(wrapper.text()).toContain("请求编号：req_device_list");
    expect(wrapper.text()).toContain("重试读取");
    wrapper.unmount();
  });

  it("renders live frames and effective fps from the shared device stream", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    const options = createStream.mock.calls[0]?.[0] as MockStreamOptions;
    options.onStatus({ state: "live", attempt: 0, effectiveFps: 1.9 });
    options.onFrame({
      blob: new Blob(["live-png"], { type: "image/png" }),
      capturedAt: "2026-07-29T03:00:01Z",
      sequence: 42,
      effectiveFps: 1.9,
    });
    await flushPromises();

    expect(wrapper.text()).toContain("实时 · 1.9 FPS");
    expect(wrapper.get("img").attributes("src")).toBe("blob:android-screen");
    expect(wrapper.text()).toContain("画面持续更新");
    wrapper.unmount();
  });

  it("pauses and resumes the stream without using device control actions", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    const options = createStream.mock.calls[0]?.[0] as MockStreamOptions;
    options.onStatus({ state: "live", attempt: 0, effectiveFps: 2 });
    await flushPromises();

    await wrapper.get("button.stream-toggle-button").trigger("click");
    expect(streamControllers[0]?.pause).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("已暂停");

    await wrapper.get("button.stream-toggle-button").trigger("click");
    expect(streamControllers[0]?.resume).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("keeps single-frame fallback available when live monitoring is disabled", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    const options = createStream.mock.calls[0]?.[0] as MockStreamOptions;
    options.onStatus({ state: "disabled", attempt: 0, effectiveFps: null });
    options.onFailure({
      code: "ANDROID_STREAM_DISABLED",
      message: "实时监看未启用，当前仍可获取单帧",
      retryable: false,
      closeCode: 4503,
    });
    await flushPromises();

    expect(wrapper.text()).toContain("实时监看未启用");
    expect(wrapper.find("img").exists()).toBe(true);
    await wrapper.get("button.single-frame-button").trigger("click");
    await flushPromises();
    expect(getScreen).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("stops the stream and releases the current frame when the page unmounts", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    wrapper.unmount();

    expect(streamControllers[0]?.stop).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:android-screen");
  });

  it("stops the stream while hidden and reconnects when the page becomes visible", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get");
    visibility.mockReturnValue("visible");
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    visibility.mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(streamControllers[0]?.stop).toHaveBeenCalledOnce();

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(createStream).toHaveBeenCalledTimes(2);
    expect(streamControllers[1]?.start).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("rebuilds the stream with the new project id after project switching", async () => {
    const wrapper = mount(AndroidDeviceMonitorPage, { props: { projectId: "project-1" } });
    await flushPromises();

    await wrapper.setProps({ projectId: "project-2" });
    await flushPromises();

    expect(streamControllers[0]?.stop).toHaveBeenCalledOnce();
    expect(list).toHaveBeenLastCalledWith("project-2", expect.any(AbortSignal));
    expect(createStream).toHaveBeenLastCalledWith(
      expect.objectContaining({ projectId: "project-2", deviceRef: "v1_online" }),
    );
    wrapper.unmount();
  });
});
