import { ApiError, apiClient } from "@/shared/api/client";

export type AndroidDeviceState = string;

export interface AndroidDevice {
  deviceRef: string;
  displayName: string;
  state: AndroidDeviceState;
  model: string | null;
  infoAvailable: boolean;
  infoError: string | null;
}

export interface AndroidDeviceListResponse {
  items: AndroidDevice[];
  total: number;
}

export interface AndroidScreenResponse {
  blob: Blob;
  capturedAt: string | null;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function decodeAndroidDevice(value: unknown): AndroidDevice {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid android device");
  }
  const item = value as Record<string, unknown>;
  if (typeof item.deviceRef !== "string" || typeof item.displayName !== "string") {
    throw new Error("invalid android device identity");
  }
  return {
    deviceRef: item.deviceRef,
    displayName: item.displayName,
    state: typeof item.state === "string" ? item.state : "unknown",
    model: asNullableString(item.model),
    infoAvailable: item.infoAvailable === true,
    infoError: asNullableString(item.infoError),
  };
}

export function decodeAndroidDeviceList(value: unknown): AndroidDeviceListResponse {
  if (typeof value !== "object" || value === null) {
    throw new Error("invalid android device list");
  }
  const body = value as Record<string, unknown>;
  if (!Array.isArray(body.items)) {
    throw new Error("invalid android device items");
  }
  const items = body.items.map(decodeAndroidDevice);
  return {
    items,
    total: typeof body.total === "number" ? body.total : items.length,
  };
}

export const androidDevicesApi = {
  list(projectId: string, signal?: AbortSignal): Promise<AndroidDeviceListResponse> {
    const init: RequestInit = {};
    if (signal) init.signal = signal;
    return apiClient.get(
      `/api/v1/projects/${encodeURIComponent(projectId)}/android-devices`,
      decodeAndroidDeviceList,
      init,
    );
  },

  async getScreen(
    projectId: string,
    deviceRef: string,
    signal?: AbortSignal,
  ): Promise<AndroidScreenResponse> {
    const init: RequestInit = { headers: { Accept: "image/png" } };
    if (signal) init.signal = signal;
    const response = await apiClient.getBlobResponse(
      `/api/v1/projects/${encodeURIComponent(projectId)}/android-devices/${encodeURIComponent(deviceRef)}/screen`,
      init,
    );
    return {
      blob: response.blob,
      capturedAt: response.headers.get("X-Captured-At"),
    };
  },
};

export function isAndroidRequestCancelled(error: unknown): boolean {
  return error instanceof ApiError && error.code === "REQUEST_CANCELLED";
}
