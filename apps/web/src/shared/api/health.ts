import { apiClient, type ApiClient } from "./client";

export interface LiveHealth {
  status: "ok";
}

export interface ReadyHealth {
  status: "ok";
  checks: {
    database: "ok";
    migrations: "ok";
  };
}

function decodeLiveHealth(value: unknown): LiveHealth {
  if (typeof value === "object" && value !== null && "status" in value && value.status === "ok") {
    return { status: "ok" };
  }
  throw new Error("invalid live health response");
}

function decodeReadyHealth(value: unknown): ReadyHealth {
  if (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    value.status === "ok" &&
    "checks" in value &&
    typeof value.checks === "object" &&
    value.checks !== null &&
    "database" in value.checks &&
    value.checks.database === "ok" &&
    "migrations" in value.checks &&
    value.checks.migrations === "ok"
  ) {
    return {
      status: "ok",
      checks: { database: "ok", migrations: "ok" },
    };
  }
  throw new Error("invalid ready health response");
}

export function getLiveHealth(client: ApiClient = apiClient): Promise<LiveHealth> {
  return client.get("/health/live", decodeLiveHealth);
}

export function getReadyHealth(client: ApiClient = apiClient): Promise<ReadyHealth> {
  return client.get("/health/ready", decodeReadyHealth);
}
