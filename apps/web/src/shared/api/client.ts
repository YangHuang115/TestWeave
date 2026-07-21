export interface StandardErrorBody {
  code: string;
  message: string;
  requestId: string;
  retryable: boolean;
  details: unknown;
}

interface ApiErrorOptions extends StandardErrorBody {
  status: number;
}

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string;
  readonly retryable: boolean;
  readonly details: unknown;
  readonly status: number;

  constructor(options: ApiErrorOptions) {
    super(options.message);
    this.name = "ApiError";
    this.code = options.code;
    this.requestId = options.requestId;
    this.retryable = options.retryable;
    this.details = options.details;
    this.status = options.status;
  }
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export type ResponseDecoder<T> = (value: unknown) => T;

interface ApiClientOptions {
  baseUrl?: string;
  timeoutMs?: number;
  fetcher?: Fetcher;
  requestIdFactory?: () => string;
}

function defaultRequestId(): string {
  return `req_ui_${globalThis.crypto.randomUUID().replaceAll("-", "")}`;
}

function isStandardErrorBody(value: unknown): value is StandardErrorBody {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.code === "string" &&
    typeof candidate.message === "string" &&
    typeof candidate.requestId === "string" &&
    typeof candidate.retryable === "boolean" &&
    (candidate.details === null || "details" in candidate)
  );
}

async function readJson(response: Response, signal: AbortSignal): Promise<unknown> {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    return null;
  }
}

function getCsrfTokenFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const match = document.cookie.match(/(^|;\s*)xsrf_token=([^;]*)/);
  return match && match[2] ? decodeURIComponent(match[2]) : null;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetcher: Fetcher;
  private readonly requestIdFactory: () => string;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl?.replace(/\/$/, "") ?? "";
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
    this.requestIdFactory = options.requestIdFactory ?? defaultRequestId;
  }

  async get<T>(
    path: string,
    decoder: ResponseDecoder<T>,
    init: Omit<RequestInit, "method"> = {},
  ): Promise<T> {
    return this.request<T>(path, decoder, { ...init, method: "GET" });
  }

  async post<T>(
    path: string,
    decoder: ResponseDecoder<T>,
    body?: unknown,
    init: Omit<RequestInit, "method" | "body"> = {},
  ): Promise<T> {
    const bodyInit: RequestInit = { ...init, method: "POST" };
    if (body !== undefined) {
      bodyInit.body = JSON.stringify(body);
      const headers = new Headers(bodyInit.headers);
      headers.set("Content-Type", "application/json");
      bodyInit.headers = headers;
    }
    return this.request<T>(path, decoder, bodyInit);
  }

  async patch<T>(
    path: string,
    decoder: ResponseDecoder<T>,
    body?: unknown,
    init: Omit<RequestInit, "method" | "body"> = {},
  ): Promise<T> {
    const bodyInit: RequestInit = { ...init, method: "PATCH" };
    if (body !== undefined) {
      bodyInit.body = JSON.stringify(body);
      const headers = new Headers(bodyInit.headers);
      headers.set("Content-Type", "application/json");
      bodyInit.headers = headers;
    }
    return this.request<T>(path, decoder, bodyInit);
  }

  async put<T>(
    path: string,
    decoder: ResponseDecoder<T>,
    body?: unknown,
    init: Omit<RequestInit, "method" | "body"> = {},
  ): Promise<T> {
    const bodyInit: RequestInit = { ...init, method: "PUT" };
    if (body !== undefined) {
      bodyInit.body = JSON.stringify(body);
      const headers = new Headers(bodyInit.headers);
      headers.set("Content-Type", "application/json");
      bodyInit.headers = headers;
    }
    return this.request<T>(path, decoder, bodyInit);
  }

  async delete<T>(
    path: string,
    decoder: ResponseDecoder<T>,
    init: Omit<RequestInit, "method"> = {},
  ): Promise<T> {
    return this.request<T>(path, decoder, { ...init, method: "DELETE" });
  }

  async request<T>(path: string, decoder: ResponseDecoder<T>, init: RequestInit = {}): Promise<T> {
    const requestId = this.requestIdFactory();
    if (init.signal?.aborted) {
      throw new ApiError({
        code: "REQUEST_CANCELLED",
        message: "请求已取消",
        requestId,
        retryable: false,
        details: null,
        status: 0,
      });
    }

    const controller = new AbortController();
    let abortCause: "caller" | "timeout" | null = null;
    const timeout = globalThis.setTimeout(() => {
      if (!controller.signal.aborted) {
        abortCause = "timeout";
        controller.abort();
      }
    }, this.timeoutMs);
    const abortFromCaller = (): void => {
      if (!controller.signal.aborted) {
        abortCause = "caller";
        controller.abort(init.signal?.reason);
      }
    };
    init.signal?.addEventListener("abort", abortFromCaller, { once: true });

    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("X-Request-ID", requestId);

    // 对写请求自动设置 CSRF 头
    if (["POST", "PUT", "PATCH", "DELETE"].includes(init.method ?? "")) {
      const csrfToken = getCsrfTokenFromCookie();
      if (csrfToken) {
        headers.set("X-CSRF-Token", csrfToken);
      }
    }

    try {
      const response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        credentials: "include",
        headers,
        signal: controller.signal,
      });
      const body = await readJson(response, controller.signal);
      if (!response.ok) {
        if (isStandardErrorBody(body)) {
          throw new ApiError({ ...body, status: response.status });
        }
        throw new ApiError({
          code: "HTTP_ERROR",
          message: "服务暂时无法完成请求",
          requestId: response.headers.get("X-Request-ID") ?? requestId,
          retryable: response.status >= 500,
          details: null,
          status: response.status,
        });
      }
      try {
        return decoder(body);
      } catch {
        throw new ApiError({
          code: "INVALID_RESPONSE",
          message: "服务返回了无法识别的数据",
          requestId: response.headers.get("X-Request-ID") ?? requestId,
          retryable: true,
          details: null,
          status: response.status,
        });
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (abortCause === "caller") {
        throw new ApiError({
          code: "REQUEST_CANCELLED",
          message: "请求已取消",
          requestId,
          retryable: false,
          details: null,
          status: 0,
        });
      }
      const timedOut = abortCause === "timeout";
      throw new ApiError({
        code: timedOut ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
        message: timedOut ? "请求超时，请稍后重试" : "无法连接服务，请检查网络后重试",
        requestId,
        retryable: true,
        details: null,
        status: 0,
      });
    } finally {
      globalThis.clearTimeout(timeout);
      init.signal?.removeEventListener("abort", abortFromCaller);
    }
  }
}

export const apiClient = new ApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});
