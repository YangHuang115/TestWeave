import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "./client";

function parseStatus(value: unknown): { status: string } {
  if (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    typeof value.status === "string"
  ) {
    return { status: value.status };
  }
  throw new Error("invalid status response");
}

function responseWhoseBodyWaitsForAbort(
  signal: AbortSignal | null | undefined,
  onRead: () => void,
): Response {
  const response = new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  vi.spyOn(response, "json").mockImplementation(
    () =>
      new Promise((_resolve, reject) => {
        onRead();
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
          once: true,
        });
      }),
  );
  return response;
}

describe("ApiClient", () => {
  it("sends credentials and a traceable request id", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_ui_123" });

    await client.get("/health/live", parseStatus);

    expect(fetcher).toHaveBeenCalledOnce();
    const [, init] = fetcher.mock.calls[0]!;
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).get("X-Request-ID")).toBe("req_ui_123");
  });

  it("converts the standard server error without discarding its request id", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "SERVICE_NOT_READY",
          message: "服务暂未就绪，请稍后重试",
          requestId: "req_server_456",
          retryable: true,
          details: null,
        }),
        {
          status: 503,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": "req_server_456",
          },
        },
      ),
    );
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_ui_123" });

    const request = client.get("/health/ready", parseStatus);

    await expect(request).rejects.toMatchObject({
      name: "ApiError",
      code: "SERVICE_NOT_READY",
      message: "服务暂未就绪，请稍后重试",
      requestId: "req_server_456",
      retryable: true,
      status: 503,
    });
  });

  it("uses a stable client error when the response is not a valid error envelope", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("gateway unavailable", { status: 502 }));
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_ui_fallback" });

    const request = client.get("/health/live", parseStatus);

    await expect(request).rejects.toMatchObject({
      code: "HTTP_ERROR",
      requestId: "req_ui_fallback",
      status: 502,
    });
  });

  it("rejects a successful response that fails its runtime decoder", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("maintenance", { status: 200 }));
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_invalid_response" });

    const request = client.get("/health/live", parseStatus);

    await expect(request).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      requestId: "req_invalid_response",
      retryable: true,
      status: 200,
    });
  });

  it("does not start a request when the caller signal is already aborted", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_cancelled_before" });

    const request = client.get("/health/live", parseStatus, {
      signal: AbortSignal.abort(),
    });

    await expect(request).rejects.toMatchObject({
      code: "REQUEST_CANCELLED",
      requestId: "req_cancelled_before",
      retryable: false,
      status: 0,
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("distinguishes an in-flight caller cancellation from a retryable network error", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const client = new ApiClient({
      fetcher,
      requestIdFactory: () => "req_cancelled_during",
      timeoutMs: 25,
    });
    const controller = new AbortController();

    const request = client.get("/health/live", parseStatus, { signal: controller.signal });
    controller.abort();

    await expect(request).rejects.toMatchObject({
      code: "REQUEST_CANCELLED",
      requestId: "req_cancelled_during",
      retryable: false,
      status: 0,
    });
  });

  it("preserves caller cancellation while reading a successful response body", async () => {
    const bodyRead = Promise.withResolvers<void>();
    const fetcher = vi.fn<typeof fetch>().mockImplementation((_input, init) =>
      Promise.resolve(
        responseWhoseBodyWaitsForAbort(init?.signal, () => {
          bodyRead.resolve();
        }),
      ),
    );
    const client = new ApiClient({
      fetcher,
      requestIdFactory: () => "req_cancelled_body",
    });
    const controller = new AbortController();

    const request = client.get("/health/live", parseStatus, { signal: controller.signal });
    await bodyRead.promise;
    controller.abort();

    await expect(request).rejects.toMatchObject({
      code: "REQUEST_CANCELLED",
      requestId: "req_cancelled_body",
      retryable: false,
      status: 0,
    });
  });

  it("preserves timeout classification while reading a successful response body", async () => {
    const bodyRead = Promise.withResolvers<void>();
    const fetcher = vi.fn<typeof fetch>().mockImplementation((_input, init) =>
      Promise.resolve(
        responseWhoseBodyWaitsForAbort(init?.signal, () => {
          bodyRead.resolve();
        }),
      ),
    );
    const client = new ApiClient({
      fetcher,
      requestIdFactory: () => "req_timeout_body",
      timeoutMs: 10,
    });

    const request = client.get("/health/live", parseStatus);
    await bodyRead.promise;

    await expect(request).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      requestId: "req_timeout_body",
      retryable: true,
      status: 0,
    });
  });

  it("automatically attaches X-CSRF-Token header on write requests if cookie exists", async () => {
    document.cookie = "xsrf_token=test-csrf-12345; path=/";

    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient({ fetcher, requestIdFactory: () => "req_write_1" });

    await client.post("/projects", parseStatus, { key: "NEW" });
    expect(fetcher).toHaveBeenCalledOnce();
    const [, init] = fetcher.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("test-csrf-12345");
    expect(init?.body).toBe(JSON.stringify({ key: "NEW" }));

    document.cookie = "xsrf_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/";
  });
});
