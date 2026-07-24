import type { ExecutionResult } from "./types";

export const RESULT_LABEL: Record<ExecutionResult, string> = {
  PASSED: "通过",
  FAILED: "失败",
  BLOCKED: "阻塞",
  SKIPPED: "跳过",
  NOT_RUN: "未执行",
};

export const RESULT_TONE: Record<
  ExecutionResult,
  "success" | "danger" | "warning" | "neutral" | "info"
> = {
  PASSED: "success",
  FAILED: "danger",
  BLOCKED: "warning",
  SKIPPED: "neutral",
  NOT_RUN: "info",
};

// 后端 current_result 为 null 时界面计算为 NOT_RUN
export function normalizeResult(r: ExecutionResult | null | undefined): ExecutionResult {
  return r ?? "NOT_RUN";
}
