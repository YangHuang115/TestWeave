export type AndroidStreamState =
  "connecting" | "live" | "reconnecting" | "paused" | "offline" | "error" | "disabled";

export interface AndroidStreamStatus {
  state: AndroidStreamState;
  attempt: number;
  effectiveFps: number | null;
}

export interface AndroidStreamFrame {
  blob: Blob;
  capturedAt: string;
  sequence: number;
  effectiveFps: number | null;
}

export interface AndroidStreamFailure {
  code: string;
  message: string;
  retryable: boolean;
  closeCode: number | null;
}

export interface AndroidDeviceStreamController {
  start(): void;
  pause(): void;
  resume(): void;
  stop(): void;
}

interface AndroidFrameMeta {
  sequence: number;
  capturedAt: string;
  contentType: "image/png";
  byteLength: number;
  effectiveFps: number | null;
}

interface AndroidStreamSocket {
  binaryType: BinaryType;
  readonly readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  close(code?: number, reason?: string): void;
}

type SocketFactory = (url: string) => AndroidStreamSocket;
type LocationLike = Pick<Location, "protocol" | "host">;

export interface AndroidDeviceStreamOptions {
  projectId: string;
  deviceRef: string;
  onStatus: (status: AndroidStreamStatus) => void;
  onFrame: (frame: AndroidStreamFrame) => void;
  onFailure: (failure: AndroidStreamFailure) => void;
  socketFactory?: SocketFactory;
  reconnectDelaysMs?: readonly number[];
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000] as const;

export function buildAndroidDeviceStreamUrl(
  projectId: string,
  deviceRef: string,
  locationLike: LocationLike = globalThis.location,
): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/api/v1/projects/${encodeURIComponent(
    projectId,
  )}/android-devices/${encodeURIComponent(deviceRef)}/stream`;
}

function defaultSocketFactory(url: string): AndroidStreamSocket {
  return new WebSocket(url);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asFiniteNonNegativeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function decodeFrameMeta(value: Record<string, unknown>): AndroidFrameMeta | null {
  const sequence = asFiniteNonNegativeNumber(value.sequence);
  const byteLength = asFiniteNonNegativeNumber(value.byteLength);
  const effectiveFps =
    value.effectiveFps === null ? null : asFiniteNonNegativeNumber(value.effectiveFps);
  if (
    sequence === null ||
    !Number.isInteger(sequence) ||
    typeof value.capturedAt !== "string" ||
    value.capturedAt.length === 0 ||
    value.contentType !== "image/png" ||
    byteLength === null ||
    !Number.isInteger(byteLength) ||
    (value.effectiveFps !== null && effectiveFps === null)
  ) {
    return null;
  }
  return {
    sequence,
    capturedAt: value.capturedAt,
    contentType: "image/png",
    byteLength,
    effectiveFps,
  };
}

function closeFailure(code: number, reason: string): AndroidStreamFailure | null {
  if (code === 4401) {
    return {
      code: "ANDROID_STREAM_UNAUTHENTICATED",
      message: "登录状态已失效，请重新登录",
      retryable: false,
      closeCode: code,
    };
  }
  if (code === 4403) {
    return {
      code: "ANDROID_STREAM_FORBIDDEN",
      message: "你没有当前项目的设备查看权限",
      retryable: false,
      closeCode: code,
    };
  }
  if (code === 4404) {
    return {
      code: "ANDROID_STREAM_DEVICE_NOT_FOUND",
      message: "设备引用已失效，请重新读取设备列表",
      retryable: false,
      closeCode: code,
    };
  }
  if (code === 4409) {
    return {
      code: "ANDROID_STREAM_DEVICE_OFFLINE",
      message: "设备当前离线或未授权",
      retryable: true,
      closeCode: code,
    };
  }
  if (code === 4503) {
    return {
      code: "ANDROID_STREAM_DISABLED",
      message: "实时监看未启用，当前仍可获取单帧",
      retryable: false,
      closeCode: code,
    };
  }
  if (code === 1000) {
    return {
      code: "ANDROID_STREAM_CLOSED",
      message: reason || "实时连接已关闭",
      retryable: true,
      closeCode: code,
    };
  }
  return null;
}

class BrowserAndroidDeviceStream implements AndroidDeviceStreamController {
  private readonly options: AndroidDeviceStreamOptions;
  private readonly socketFactory: SocketFactory;
  private readonly reconnectDelaysMs: readonly number[];
  private socket: AndroidStreamSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectIndex = 0;
  private pendingMeta: AndroidFrameMeta | null = null;
  private stopped = true;
  private paused = false;

  constructor(options: AndroidDeviceStreamOptions) {
    this.options = options;
    this.socketFactory = options.socketFactory ?? defaultSocketFactory;
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
  }

  start(): void {
    if (!this.stopped || this.socket || this.reconnectTimer) return;
    this.stopped = false;
    this.paused = false;
    this.reconnectIndex = 0;
    this.connect(false);
  }

  pause(): void {
    if (this.stopped || this.paused) return;
    this.paused = true;
    this.reconnectIndex = 0;
    this.clearReconnectTimer();
    this.closeSocket(1000, "client pause");
    this.emitStatus("paused", 0, null);
  }

  resume(): void {
    if (this.stopped || !this.paused) return;
    this.paused = false;
    this.reconnectIndex = 0;
    this.connect(false);
  }

  stop(): void {
    if (this.stopped && !this.socket && !this.reconnectTimer) return;
    this.stopped = true;
    this.paused = false;
    this.pendingMeta = null;
    this.clearReconnectTimer();
    this.closeSocket(1000, "client stop");
  }

  private connect(reconnecting: boolean): void {
    if (this.stopped || this.paused) return;
    this.clearReconnectTimer();
    const attempt = reconnecting ? this.reconnectIndex : 0;
    this.emitStatus(reconnecting ? "reconnecting" : "connecting", attempt, null);

    let socket: AndroidStreamSocket;
    try {
      socket = this.socketFactory(
        buildAndroidDeviceStreamUrl(this.options.projectId, this.options.deviceRef),
      );
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;
    socket.binaryType = "blob";
    socket.onmessage = (event) => this.handleMessage(socket, event.data);
    socket.onerror = () => {
      // Browser WebSocket errors do not expose stable details. The close event
      // owns retry and user-visible state so failures are not reported twice.
    };
    socket.onclose = (event) => this.handleClose(socket, event);
  }

  private handleMessage(socket: AndroidStreamSocket, data: unknown): void {
    if (this.socket !== socket || this.stopped || this.paused) return;
    if (typeof data === "string") {
      if (this.pendingMeta) {
        this.pendingMeta = null;
        this.failProtocol(socket, "实时画面元数据后未紧邻对应二进制帧");
        return;
      }
      this.handleTextMessage(socket, data);
      return;
    }
    if (data instanceof Blob) {
      this.handleBinaryMessage(socket, data);
      return;
    }
    this.failProtocol(socket, "实时画面返回了不支持的二进制格式");
  }

  private handleTextMessage(socket: AndroidStreamSocket, data: string): void {
    let value: unknown;
    try {
      value = JSON.parse(data);
    } catch {
      this.failProtocol(socket, "实时画面返回了无效事件");
      return;
    }
    if (!isRecord(value) || typeof value.type !== "string") {
      this.failProtocol(socket, "实时画面事件缺少类型");
      return;
    }
    if (value.type === "stream.ready") {
      this.emitStatus(
        this.reconnectIndex > 0 ? "reconnecting" : "connecting",
        this.reconnectIndex,
        null,
      );
      return;
    }
    if (value.type === "frame.meta") {
      const meta = decodeFrameMeta(value);
      if (!meta) {
        this.failProtocol(socket, "实时画面元数据无效");
        return;
      }
      this.pendingMeta = meta;
      return;
    }
    if (value.type === "stream.error") {
      const retryable = value.retryable !== false;
      this.options.onFailure({
        code: typeof value.code === "string" ? value.code : "ANDROID_STREAM_ERROR",
        message:
          typeof value.message === "string" && value.message.length > 0
            ? value.message
            : "实时画面暂时不可用",
        retryable,
        closeCode: null,
      });
      this.emitStatus(retryable ? "reconnecting" : "error", this.reconnectIndex, null);
    }
  }

  private handleBinaryMessage(socket: AndroidStreamSocket, blob: Blob): void {
    const meta = this.pendingMeta;
    this.pendingMeta = null;
    if (!meta || blob.size !== meta.byteLength) {
      this.failProtocol(socket, "实时画面与元数据无法配对");
      return;
    }
    this.reconnectIndex = 0;
    this.options.onFrame({
      blob,
      capturedAt: meta.capturedAt,
      sequence: meta.sequence,
      effectiveFps: meta.effectiveFps,
    });
    this.emitStatus("live", 0, meta.effectiveFps);
  }

  private handleClose(socket: AndroidStreamSocket, event: CloseEvent): void {
    if (this.socket !== socket) return;
    this.socket = null;
    this.pendingMeta = null;
    if (this.stopped || this.paused) return;

    const failure = closeFailure(event.code, event.reason);
    if (failure) {
      this.options.onFailure(failure);
      if (!failure.retryable) {
        this.emitStatus(event.code === 4503 ? "disabled" : "error", 0, null);
        return;
      }
      if (event.code === 4409) {
        this.scheduleReconnect("offline");
        return;
      }
    }
    this.scheduleReconnect();
  }

  private scheduleReconnect(waitingState: "reconnecting" | "offline" = "reconnecting"): void {
    if (this.stopped || this.paused || this.reconnectTimer) return;
    if (this.reconnectIndex >= this.reconnectDelaysMs.length) {
      this.options.onFailure({
        code: "ANDROID_STREAM_RECONNECT_EXHAUSTED",
        message: "实时连接多次重试仍未恢复，可继续使用单帧画面",
        retryable: true,
        closeCode: null,
      });
      this.emitStatus("error", this.reconnectIndex, null);
      return;
    }
    const delay = this.reconnectDelaysMs[this.reconnectIndex] ?? 0;
    this.reconnectIndex += 1;
    this.emitStatus(waitingState, this.reconnectIndex, null);
    this.reconnectTimer = globalThis.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect(true);
    }, delay);
  }

  private failProtocol(socket: AndroidStreamSocket, message: string): void {
    this.options.onFailure({
      code: "ANDROID_STREAM_PROTOCOL_ERROR",
      message,
      retryable: false,
      closeCode: 1002,
    });
    this.emitStatus("error", this.reconnectIndex, null);
    if (this.socket === socket) {
      this.socket = null;
      socket.close(1002, "protocol error");
    }
  }

  private emitStatus(
    state: AndroidStreamState,
    attempt: number,
    effectiveFps: number | null,
  ): void {
    this.options.onStatus({ state, attempt, effectiveFps });
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      globalThis.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private closeSocket(code: number, reason: string): void {
    const socket = this.socket;
    this.socket = null;
    this.pendingMeta = null;
    socket?.close(code, reason);
  }
}

export function createAndroidDeviceStream(
  options: AndroidDeviceStreamOptions,
): AndroidDeviceStreamController {
  return new BrowserAndroidDeviceStream(options);
}
