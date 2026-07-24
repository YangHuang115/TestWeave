import { apiClient } from "../../shared/api/client";
import type {
  AiArtifactContent,
  AiDesignRecordSummary,
  AiDesignStageKey,
  AiRecordListResponse,
  AiSetRevision,
  AiWorkbenchState,
} from "./types";

function base(projectId: string, taskId: string): string {
  return `/api/v1/projects/${projectId}/test-tasks/${taskId}/ai-design`;
}

export const aiTestDesignApi = {
  listRecords(projectId: string, taskId: string): Promise<AiRecordListResponse> {
    return apiClient.get(`${base(projectId, taskId)}/records`, (data) => data as AiRecordListResponse);
  },

  deleteRecord(projectId: string, taskId: string, recordId: string): Promise<void> {
    return apiClient.delete(`${base(projectId, taskId)}/records/${recordId}`);
  },

  createRecord(
    projectId: string,
    taskId: string,
    reviewMode: "TRACEABLE" | "INTRINSIC",
    idempotencyKey: string,
  ): Promise<AiDesignRecordSummary> {
    return apiClient.post(
      `${base(projectId, taskId)}/records`,
      (data) => data as AiDesignRecordSummary,
      { reviewMode },
      { headers: { "Idempotency-Key": idempotencyKey } },
    );
  },

  getRecord(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
  ): Promise<AiWorkbenchState> {
    const params = new URLSearchParams({ stage });
    return apiClient.get(
      `${base(projectId, taskId)}/records/${recordId}?${params.toString()}`,
      (data) => data as AiWorkbenchState,
    );
  },

  saveRevision(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    payload: {
      baseSetRevisionId: string;
      expectedSetHash: string;
      items: AiArtifactContent[];
    },
  ): Promise<AiSetRevision> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/revisions`,
      (data) => data as AiSetRevision,
      payload,
    );
  },

  acceptStage(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    payload: {
      setRevisionId: string;
      expectedCurrentSetRevisionId: string | null;
      decisionSnapshot: Record<string, unknown>;
    },
  ): Promise<{ status: string; currentSetRevisionId: string; rowVersion: number }> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/accept`,
      (data) => data as { status: string; currentSetRevisionId: string; rowVersion: number },
      payload,
    );
  },

  createFeedback(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    payload: Record<string, unknown>,
  ): Promise<{ id: string; status: string }> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/feedback`,
      (data) => data as { id: string; status: string },
      payload,
    );
  },

  createFieldLock(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    payload: { itemId: string; revisionId: string; jsonPointer: string },
  ): Promise<{ id: string; status: string }> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/field-locks`,
      (data) => data as { id: string; status: string },
      payload,
    );
  },

  releaseFieldLock(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    lockId: string,
  ): Promise<{ id: string; status: string }> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/field-locks/${lockId}/release`,
      (data) => data as { id: string; status: string },
    );
  },

  createRegenerationRequest(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
    payload: {
      targetItemStableKeys: string[];
      baseSetRevisionId: string;
      feedbackIds: string[];
    },
    idempotencyKey: string,
  ): Promise<{ id: string; status: string }> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/regeneration-requests`,
      (data) => data as { id: string; status: string },
      payload,
      { headers: { "Idempotency-Key": idempotencyKey } },
    );
  },

  retryStage(
    projectId: string,
    taskId: string,
    recordId: string,
    stage: AiDesignStageKey,
  ): Promise<Record<string, unknown>> {
    return apiClient.post(
      `${base(projectId, taskId)}/records/${recordId}/stages/${stage}/retry`,
      (data) => data as Record<string, unknown>,
    );
  },

  getDiff(
    projectId: string,
    runId: string,
    setRevisionId: string,
    baseSetRevisionId: string,
  ): Promise<Record<string, unknown>> {
    const params = new URLSearchParams({ baseSetRevisionId });
    return apiClient.get(
      `/api/v1/projects/${projectId}/ai-runs/${runId}/revision-sets/${setRevisionId}/diff?${params.toString()}`,
      (data) => data as Record<string, unknown>,
    );
  },
};
