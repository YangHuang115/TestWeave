import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildAndroidDeviceStreamUrl,
  createAndroidDeviceStream,
  type AndroidStreamFrame,
  type AndroidStreamStatus,
} from "./androidDeviceStream";

class FakeSocket {
  binaryType: BinaryType = "blob";
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  readonly close = vi.fn((code: number = 1000, reason: string = "") => {
    this.readyState = 3;
    this.onclose?.({ code, reason, wasClean: code === 1000 } as CloseEvent);
  });

  emitJson(value: unknown): void {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }

  emitBlob(value: Blob): void {
    this.onmessage?.({ data: value } as MessageEvent);
  }

  emitClose(code: number, reason = ""): void {
    this.readyState = 3;
    this.onclose?.({ code, reason, wasClean: code === 1000 } as CloseEvent);
  }
}

afterEach(() => {
  vi.useRealTimers();
});

describe("androidDeviceStream", () => {
  it("builds a same-origin websocket URL with encoded path segments", () => {
    expect(
      buildAndroidDeviceStreamUrl("project one", "v1/device", {
        protocol: "https:",
        host: "testweave.local",
      }),
    ).toBe(
      "wss://testweave.local/api/v1/projects/project%20one/android-devices/v1%2Fdevice/stream",
    );
  });

  it("pairs frame metadata with the following PNG binary message", () => {
    const sockets: FakeSocket[] = [];
    const statuses: AndroidStreamStatus[] = [];
    const frames: AndroidStreamFrame[] = [];
    const failures: string[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: (status) => statuses.push(status),
      onFrame: (frame) => frames.push(frame),
      onFailure: (failure) => failures.push(failure.code),
    });

    controller.start();
    sockets[0]?.emitJson({ type: "stream.ready" });
    expect(statuses.at(-1)?.state).toBe("connecting");
    sockets[0]?.emitJson({
      type: "frame.meta",
      sequence: 42,
      capturedAt: "2026-07-29T03:00:01Z",
      contentType: "image/png",
      byteLength: 8,
      effectiveFps: 1.9,
    });
    const blob = new Blob(["png-data"], { type: "image/png" });
    sockets[0]?.emitBlob(blob);

    expect(statuses[0]?.state).toBe("connecting");
    expect(statuses.at(-1)).toEqual({ state: "live", attempt: 0, effectiveFps: 1.9 });
    expect(frames).toEqual([
      {
        blob,
        capturedAt: "2026-07-29T03:00:01Z",
        sequence: 42,
        effectiveFps: 1.9,
      },
    ]);
    expect(failures).toEqual([]);
    controller.stop();
  });

  it("supports explicit pause and resume", () => {
    const sockets: FakeSocket[] = [];
    const statuses: AndroidStreamStatus[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: (status) => statuses.push(status),
      onFrame: vi.fn(),
      onFailure: vi.fn(),
    });

    controller.start();
    controller.pause();
    controller.resume();

    expect(sockets).toHaveLength(2);
    expect(sockets[0]?.close).toHaveBeenCalledWith(1000, "client pause");
    expect(statuses.map((item) => item.state)).toEqual(["connecting", "paused", "connecting"]);
    controller.stop();
  });

  it("reports stream-disabled close without retrying", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const statuses: AndroidStreamStatus[] = [];
    const failures: string[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: (status) => statuses.push(status),
      onFrame: vi.fn(),
      onFailure: (failure) => failures.push(failure.code),
      reconnectDelaysMs: [10, 20],
    });

    controller.start();
    sockets[0]?.emitClose(4503, "stream disabled");
    vi.runAllTimers();

    expect(statuses.at(-1)?.state).toBe("disabled");
    expect(failures).toEqual(["ANDROID_STREAM_DISABLED"]);
    expect(sockets).toHaveLength(1);
  });

  it("reconnects after a transient abnormal close", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const statuses: AndroidStreamStatus[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: (status) => statuses.push(status),
      onFrame: vi.fn(),
      onFailure: vi.fn(),
      reconnectDelaysMs: [10, 20],
    });

    controller.start();
    sockets[0]?.emitClose(1006);

    expect(statuses.at(-1)).toEqual({
      state: "reconnecting",
      attempt: 1,
      effectiveFps: null,
    });
    vi.advanceTimersByTime(10);
    expect(sockets).toHaveLength(2);
    sockets[1]?.emitJson({ type: "stream.ready" });
    expect(statuses.at(-1)).toEqual({
      state: "reconnecting",
      attempt: 1,
      effectiveFps: null,
    });
    controller.stop();
  });

  it("does not reset the limited retry budget until a valid frame arrives", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const statuses: AndroidStreamStatus[] = [];
    const failures: string[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: (status) => statuses.push(status),
      onFrame: vi.fn(),
      onFailure: (failure) => failures.push(failure.code),
      reconnectDelaysMs: [10, 20],
    });

    controller.start();
    sockets[0]?.emitJson({ type: "stream.ready" });
    sockets[0]?.emitClose(1006);
    vi.advanceTimersByTime(10);
    sockets[1]?.emitJson({ type: "stream.ready" });
    sockets[1]?.emitClose(1006);
    vi.advanceTimersByTime(20);
    sockets[2]?.emitJson({ type: "stream.ready" });
    sockets[2]?.emitClose(1006);

    expect(sockets).toHaveLength(3);
    expect(statuses.at(-1)?.state).toBe("error");
    expect(failures).toContain("ANDROID_STREAM_RECONNECT_EXHAUSTED");
  });

  it("rejects a text event inserted between frame metadata and its binary frame", () => {
    const sockets: FakeSocket[] = [];
    const failures: string[] = [];
    const controller = createAndroidDeviceStream({
      projectId: "project-1",
      deviceRef: "v1_device",
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onStatus: vi.fn(),
      onFrame: vi.fn(),
      onFailure: (failure) => failures.push(failure.code),
    });

    controller.start();
    sockets[0]?.emitJson({
      type: "frame.meta",
      sequence: 42,
      capturedAt: "2026-07-29T03:00:01Z",
      contentType: "image/png",
      byteLength: 8,
      effectiveFps: 1.9,
    });
    sockets[0]?.emitJson({ type: "stream.error", message: "temporary" });

    expect(failures).toEqual(["ANDROID_STREAM_PROTOCOL_ERROR"]);
    expect(sockets[0]?.close).toHaveBeenCalledWith(1002, "protocol error");
  });
});
