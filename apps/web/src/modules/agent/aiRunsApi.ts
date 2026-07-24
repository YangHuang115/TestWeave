import { apiClient } from "../../shared/api/client";

export type AIRunMode = "NORMAL" | "PREVIEW";

export type CapabilityRunStatus =
  "PENDING" | "RUNNING" | "WAITING_HUMAN" | "WAITING_RETRY" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export type StepExecutionStatus =
  "PENDING" | "RUNNING" | "WAITING_HUMAN" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "SKIPPED";

export interface AIRunCreateRequest {
  runMode: AIRunMode;
  capabilityVersionId?: string;
  input: Record<string, unknown>;
}

export interface AIRunResponse {
  id: string;
  capabilityId: string;
  capabilityVersionId: string;
  projectId: string;
  runMode: AIRunMode;
  status: CapabilityRunStatus;
  idempotencyKey: string;
  requestFingerprint: string;
  executionSnapshotHash: string;
  nextEventSequence: number;
  cancelRequested: boolean;
  cancelRequestedAt: string | null;
  cancelRequestedBy: string | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  allowedActions: string[];
  errorCode: string | null;
  errorSummary: string | null;
}

export interface AIStepExecutionResponse {
  id: string;
  runId: string;
  nodeId: string;
  nodeType: "SKILL" | "TRANSFORM" | "VALIDATOR" | "HUMAN";
  nodeName: string;
  attempt: number;
  status: StepExecutionStatus;
  inputSummary: Record<string, unknown> | null;
  outputSnapshotId: string | null;
  claimOwner: string | null;
  claimExpiresAt: string | null;
  availableAt: string | null;
  retryOfId: string | null;
  retryable: boolean;
  errorCode: string | null;
  errorSummary: string | null;
  providerName: string | null;
  modelName: string | null;
  usageSnapshot: Record<string, unknown> | null;
  durationMs: number | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface AIRunEventResponse {
  id: string;
  runId: string;
  sequenceNo: number;
  eventType: string;
  stepExecutionId: string | null;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface AIRunDetailResponse {
  run: AIRunResponse;
  steps: AIStepExecutionResponse[];
  finalOutput: Record<string, unknown> | null;
  executionSnapshot: Record<string, unknown>;
}

export interface AIRunEventsPollResponse {
  events: AIRunEventResponse[];
  nextSequenceNo: number;
  hasMore: boolean;
}

export interface HumanDecisionSubmitRequest {
  action: "APPROVE" | "REJECT";
  decision: Record<string, unknown>;
}

export const aiRunsApi = {
  async createRun(
    projectId: string,
    capabilityId: string,
    req: AIRunCreateRequest,
    idempotencyKey: string,
  ): Promise<AIRunResponse> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/ai-capabilities/${capabilityId}/runs`,
      (data) => data as AIRunResponse,
      req,
      {
        headers: {
          "Idempotency-Key": idempotencyKey,
        },
      },
    );
  },

  async getRunDetail(projectId: string, runId: string): Promise<AIRunDetailResponse> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/ai-runs/${runId}`,
      (data) => data as AIRunDetailResponse,
    );
  },

  async pollEvents(
    projectId: string,
    runId: string,
    afterSequence = 0,
    limit = 100,
  ): Promise<AIRunEventsPollResponse> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/ai-runs/${runId}/events?afterSequence=${afterSequence}&limit=${limit}`,
      (data) => data as AIRunEventsPollResponse,
    );
  },

  async cancelRun(projectId: string, runId: string): Promise<AIRunResponse> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/ai-runs/${runId}/cancel`,
      (data) => data as AIRunResponse,
    );
  },

  async submitHumanDecision(
    projectId: string,
    runId: string,
    stepExecutionId: string,
    req: HumanDecisionSubmitRequest,
  ): Promise<AIStepExecutionResponse> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/ai-runs/${runId}/steps/${stepExecutionId}/human-decision`,
      (data) => data as AIStepExecutionResponse,
      req,
    );
  },

  async retryStep(
    projectId: string,
    runId: string,
    stepExecutionId: string,
  ): Promise<AIStepExecutionResponse> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/ai-runs/${runId}/steps/${stepExecutionId}/retry`,
      (data) => data as AIStepExecutionResponse,
    );
  },
};
