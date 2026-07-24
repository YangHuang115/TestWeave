// M06 测试执行 · 前端类型定义
// 字段命名与后端响应（camelCase）保持一致，参见
// apps/server/src/testweave/api/v1/test_executions.py

export type ExecutionResult = "PASSED" | "FAILED" | "BLOCKED" | "SKIPPED" | "NOT_RUN";

export type RecordSource = "MANUAL" | "BATCH_PASS" | "CORRECTION";

export type TaskStatus =
  | "DRAFT"
  | "READY"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "COMPLETED"
  | "CANCELLED"
  | "ARCHIVED";

export interface ExecutionTaskSummary {
  id: string;
  projectId: string;
  taskNo: string | null;
  title: string;
  status: TaskStatus;
  rowVersion: number;
  ownerId: string;
  plannedEndAt: string | null;
  sourceDesignTaskId: string | null;
  sourceDesignTaskNo: string | null;
  sourceRequirementId: string | null;
  sourceRequirementTitle: string | null;
  testEnvironment: Record<string, unknown> | null;
  buildVersion: string | null;
  totalCount: number;
  notRunCount: number;
  passedCount: number;
  failedCount: number;
  blockedCount: number;
  skippedCount: number;
  executionRecordCount: number;
}

export interface ExecutionCaseStep {
  order?: number;
  action?: string;
  expectedResult?: string;
  note?: string | null;
}

export interface ExecutionCaseSummary {
  id: string;
  testCaseId: string;
  testCaseRevisionId: string;
  caseNo: string | null;
  title: string | null;
  modulePaths: string[] | null;
  precondition: string | null;
  priority: string | null;
  caseType: string | null;
  steps: ExecutionCaseStep[];
  currentResult: ExecutionResult | null;
  latestActualResult: string | null;
  latestNote: string | null;
  latestExecutedBy: string | null;
  latestExecutedAt: string | null;
  executionCount: number;
  revisionNo: string | null;
}

export interface ExecutionRecordSummary {
  id: string;
  executionCaseId: string;
  recordNo: number;
  result: ExecutionResult;
  actualResult: string | null;
  note: string | null;
  reasonCode: string | null;
  reasonText: string | null;
  executedBy: string;
  executedAt: string;
  recordSource: RecordSource;
  correctionOfRecordId: string | null;
  correctionNote: string | null;
}

export interface CompletionPreview {
  total: number;
  notRun: number;
  passed: number;
  failed: number;
  blocked: number;
  skipped: number;
  failureWithoutDefect: number;
}

export interface BatchPassItem {
  executionCaseId: string;
  status: "SUCCEEDED" | "FAILED";
  recordId?: string;
  errorCode?: string;
}

export interface BatchPassResult {
  total: number;
  succeeded: number;
  failed: number;
  items: BatchPassItem[];
}

export interface EvidenceItem {
  id: string;
  evidenceType: string;
  externalUrl: string | null;
  objectKey: string | null;
  fileName: string | null;
  mimeType: string | null;
  fileSize: number | null;
  createdAt: string | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
}

// 创建执行任务请求（design.md §10.1）
export interface CreateExecutionTaskPayload {
  sourceDesignTaskId: string;
  title: string;
  ownerId: string;
  participantIds?: string[];
  plannedStartAt?: string | null;
  plannedEndAt: string;
  priority?: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  description?: string | null;
  testEnvironment?: Record<string, unknown> | null;
  buildVersion?: string | null;
  testGoal?: string | null;
  tagsJson?: string[] | null;
  idempotencyKey: string;
}

export interface CreateRecordPayload {
  result: ExecutionResult;
  actualResult?: string | null;
  note?: string | null;
  reasonCode?: string | null;
  reasonText?: string | null;
  evidences?: Record<string, unknown>[] | null;
  idempotencyKey: string;
}

export interface CreateCorrectionPayload {
  result: ExecutionResult;
  actualResult?: string | null;
  note?: string | null;
  reasonCode?: string | null;
  reasonText?: string | null;
  correctionOfRecordId: string;
  correctionNote: string;
  idempotencyKey: string;
}

export interface BatchPassPayload {
  executionCaseIds: string[];
  idempotencyKey: string;
}
