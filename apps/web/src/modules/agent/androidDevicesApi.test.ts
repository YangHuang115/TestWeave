import { describe, expect, it } from "vitest";

import { decodeAndroidDeviceList } from "./androidDevicesApi";

describe("androidDevicesApi decoders", () => {
  it("decodes the shared device list DTO without exposing raw serials", () => {
    const result = decodeAndroidDeviceList({
      items: [
        {
          deviceRef: "v1_opaque",
          displayName: "Pixel 8",
          state: "online",
          model: "Pixel 8",
          infoAvailable: true,
          infoError: null,
        },
      ],
      total: 1,
    });

    expect(result.items[0]).toEqual({
      deviceRef: "v1_opaque",
      displayName: "Pixel 8",
      state: "online",
      model: "Pixel 8",
      infoAvailable: true,
      infoError: null,
    });
    expect(result.items[0]).not.toHaveProperty("deviceId");
  });

  it("rejects malformed list payloads", () => {
    expect(() => decodeAndroidDeviceList({ items: [{ displayName: "Pixel" }] })).toThrow();
  });
});
