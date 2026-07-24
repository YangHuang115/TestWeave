import type { AiDesignStageKey, AiDesignStageStatus, AiRunStatus } from "./types";

type StageAcceptanceItem = {
  stableKey?: string;
  questions?: Array<{ blocking?: boolean; status?: string }>;
  findings?: Array<{ decision?: string; decisionReason?: string }>;
  allowCaseGeneration?: boolean;
};

const STATUS_LABELS: Record<AiDesignStageStatus, string> = {
  NOT_GENERATED: "未生成",
  GENERATING: "生成中",
  WAITING_HUMAN: "等待人工确认",
  CANDIDATE: "候选结果",
  ACCEPTED: "已接受",
  STALE: "已过期",
  RERUN_REQUIRED: "需要重生成",
  GENERATION_FAILED: "生成失败",
};

export function stageStatusLabel(status: AiDesignStageStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function resolveRecordId(
  routeRecordId: string | undefined,
  resumeRecordId: string | null,
): string | null {
  return routeRecordId?.trim() || resumeRecordId;
}

export function shouldPollRun(status: AiRunStatus): boolean {
  return ["PENDING", "RUNNING", "WAITING_RETRY"].includes(status);
}

export function shouldPollWorkbench(
  runStatus: AiRunStatus,
  regenerationStatuses: string[],
): boolean {
  return (
    shouldPollRun(runStatus) ||
    regenerationStatuses.some((status) => status === "PENDING" || status === "RUNNING")
  );
}

export function canAcceptStage(stageKey: AiDesignStageKey, items: StageAcceptanceItem[]): boolean {
  if (items.length === 0) return false;
  if (stageKey === "requirement-analysis") {
    const analysis = items[0];
    return !(analysis?.questions ?? []).some(
      (question) => question.blocking && question.status === "PENDING",
    );
  }
  if (stageKey === "test-points") {
    return items.some(
      (item) => item.allowCaseGeneration,
    );
  }
  if (stageKey === "case-review") {
    const report = items[0];
    return !(report?.findings ?? []).some(
      (finding) =>
        finding.decision === "PENDING" ||
        (finding.decision === "REJECTED" && !finding.decisionReason?.trim()),
    );
  }
  return true;
}

export const STAGE_ROUTES: Record<AiDesignStageKey, string> = {
  "requirement-analysis": "requirement-analysis",
  "test-points": "test-points",
  "test-cases": "test-cases",
  "case-review": "case-review",
};
