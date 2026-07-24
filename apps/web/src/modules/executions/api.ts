// M06 测试执行 · API 客户端（基于项目统一 ApiClient）
// 端点前缀：/api/v1/projects/{projectId}/test-executions
// 状态流转（DRAFT->READY）复用通用 test-tasks 流转端点
// /api/v1/projects/{projectId}/test-tasks/{taskId}/transitions
import { apiClient } from "@/shared/api/client";
import type {
  BatchPassPayload,
  BatchPassResult,
  CompletionPreview,
  CreateCorrectionPayload,
  CreateExecutionTaskPayload,
  CreateRecordPayload,
  EvidenceItem,
  ExecutionCaseSummary,
  ExecutionRecordSummary,
  ExecutionTaskSummary,
  Paged,
} from "./types";

const BASE = (projectId: string) => `/api/v1/projects/${projectId}/test-executions`;

// 轻量解码器：直接断言响应形状（后端响应已做结构校验）
const asTask = (v: unknown): ExecutionTaskSummary => v as ExecutionTaskSummary;
const asPagedCases = (v: unknown): Paged<ExecutionCaseSummary> =>
  v as Paged<ExecutionCaseSummary>;
const asPagedRecords = (v: unknown): Paged<ExecutionRecordSummary> =>
  v as Paged<ExecutionRecordSummary>;
const asCompletion = (v: unknown): CompletionPreview => v as CompletionPreview;
const asBatch = (v: unknown): BatchPassResult => v as BatchPassResult;
const asRecord = (v: unknown): ExecutionRecordSummary => v as ExecutionRecordSummary;
const asEvidence = (v: unknown): EvidenceItem => v as EvidenceItem;
const asEvidenceList = (v: unknown): { items: EvidenceItem[] } =>
  v as { items: EvidenceItem[] };

interface UploadResult {
  objectKey: string;
  fileName: string;
  mimeType: string;
  fileSize: number;
  checksum: string;
}
const asUpload = (v: unknown): UploadResult => v as UploadResult;

interface ExportResult {
  exportId: string;
  status: string;
  fileObjectKey: string;
  fileName: string;
  fileSize: number;
}
const asExport = (v: unknown): ExportResult => v as ExportResult;

export async function createExecutionTask(
  projectId: string,
  payload: CreateExecutionTaskPayload,
): Promise<ExecutionTaskSummary> {
  return apiClient.post(BASE(projectId), asTask, payload);
}

export async function listExecutionTasks(
  projectId: string,
): Promise<Paged<ExecutionTaskSummary>> {
  return apiClient.get(BASE(projectId), (v) => v as Paged<ExecutionTaskSummary>);
}

export async function getExecutionTask(
  projectId: string,
  taskId: string,
): Promise<ExecutionTaskSummary> {
  return apiClient.get(`${BASE(projectId)}/${taskId}`, asTask);
}

export async function listExecutionCases(
  projectId: string,
  taskId: string,
  limit = 200,
  offset = 0,
): Promise<Paged<ExecutionCaseSummary>> {
  const qs = `?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`;
  return apiClient.get(`${BASE(projectId)}/${taskId}/cases${qs}`, asPagedCases);
}

export async function getCompletionPreview(
  projectId: string,
  taskId: string,
): Promise<CompletionPreview> {
  return apiClient.get(`${BASE(projectId)}/${taskId}/completion-preview`, asCompletion);
}

export async function completeTask(
  projectId: string,
  taskId: string,
): Promise<ExecutionTaskSummary> {
  return apiClient.post(`${BASE(projectId)}/${taskId}/complete`, asTask);
}

export async function reopenTask(
  projectId: string,
  taskId: string,
  reasonText: string,
): Promise<ExecutionTaskSummary> {
  return apiClient.post(`${BASE(projectId)}/${taskId}/reopen`, asTask, { reasonText });
}

export async function batchPass(
  projectId: string,
  taskId: string,
  payload: BatchPassPayload,
): Promise<BatchPassResult> {
  return apiClient.post(`${BASE(projectId)}/${taskId}/batch-pass`, asBatch, payload);
}

export async function createRecord(
  projectId: string,
  taskId: string,
  executionCaseId: string,
  payload: CreateRecordPayload,
): Promise<ExecutionRecordSummary> {
  return apiClient.post(
    `${BASE(projectId)}/${taskId}/cases/${executionCaseId}/records`,
    asRecord,
    payload,
  );
}

export async function createCorrection(
  projectId: string,
  taskId: string,
  executionCaseId: string,
  payload: CreateCorrectionPayload,
): Promise<ExecutionRecordSummary> {
  return apiClient.post(
    `${BASE(projectId)}/${taskId}/cases/${executionCaseId}/corrections`,
    asRecord,
    payload,
  );
}

export async function listRecords(
  projectId: string,
  taskId: string,
  executionCaseId: string,
): Promise<Paged<ExecutionRecordSummary>> {
  return apiClient.get(
    `${BASE(projectId)}/${taskId}/cases/${executionCaseId}/records`,
    asPagedRecords,
  );
}

export async function listEvidences(
  projectId: string,
  taskId: string,
  recordId: string,
): Promise<{ items: EvidenceItem[] }> {
  return apiClient.get(
    `${BASE(projectId)}/${taskId}/records/${recordId}/evidences`,
    asEvidenceList,
  );
}

export async function addExternalLinkEvidence(
  projectId: string,
  taskId: string,
  recordId: string,
  url: string,
): Promise<EvidenceItem> {
  return apiClient.post(
    `${BASE(projectId)}/${taskId}/records/${recordId}/evidences/external-link`,
    asEvidence,
    { url },
  );
}

export async function uploadEvidence(
  projectId: string,
  taskId: string,
  file: File,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  // FormData 不能走 post 的 JSON 序列化，使用底层 request
  return apiClient.request(`${BASE(projectId)}/${taskId}/evidences/uploads`, asUpload, {
    method: "POST",
    body: form,
  });
}

export async function exportExecution(
  projectId: string,
  taskId: string,
): Promise<ExportResult> {
  return apiClient.post(`${BASE(projectId)}/${taskId}/exports`, asExport);
}

// 通用 test-tasks 流转（M06 任务创建后为 DRAFT，需转为 READY）
export interface TaskTransitionResult {
  status: string;
  rowVersion?: number;
  [k: string]: unknown;
}

export async function transitionTask(
  projectId: string,
  taskId: string,
  targetStatus: string,
  rowVersion: number,
): Promise<TaskTransitionResult> {
  return apiClient.post(
    `/api/v1/projects/${projectId}/test-tasks/${taskId}/transitions`,
    (v) => v as TaskTransitionResult,
    { targetStatus, rowVersion },
  );
}
