import { apiClient } from "../../shared/api/client";

export interface TestTask {
  id: string;
  projectId: string;
  versionId: string;
  taskNo: string;
  taskType: "CASE_DESIGN" | "TEST_EXECUTION";
  status: "DRAFT" | "READY" | "IN_PROGRESS" | "BLOCKED" | "COMPLETED" | "CANCELLED" | "ARCHIVED";
  title: string;
  description: string | null;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  ownerId: string;
  plannedStartAt: string;
  plannedEndAt: string;
  actualStartedAt: string | null;
  currentCompletedAt: string | null;
  completionCount: number;
  completionNote: string | null;
  testGoal: string | null;
  excludedScope: string | null;
  tagsJson: string[] | null;
  previousStatus: string | null;
  rowVersion: number;
  createdBy: string | null;
  createdAt: string;
  updatedBy: string | null;
  updatedAt: string;
  archivedAt: string | null;
  ownerName?: string;
  isBlocked?: boolean;
  isOverdue?: boolean;
  activeBlockageReason?: string | null;
}

export interface TestTaskListResponse {
  items: TestTask[];
  total: number;
}

export interface TestTaskCreatePayload {
  title: string;
  versionId: string;
  taskType: "CASE_DESIGN" | "TEST_EXECUTION";
  ownerId: string;
  plannedStartAt?: string | null;
  plannedEndAt: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  description?: string | null;
  testGoal?: string | null;
  excludedScope?: string | null;
  tagsJson?: string[] | null;
}

export interface TestTaskUpdatePayload {
  title: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  ownerId: string;
  plannedStartAt: string;
  plannedEndAt: string;
  description?: string | null;
  testGoal?: string | null;
  excludedScope?: string | null;
  tagsJson?: string[] | null;
  rowVersion: number;
}

export interface TestTaskActivity {
  id: string;
  projectId: string;
  taskId: string;
  fromStatus: string;
  toStatus: string;
  reasonCode: string | null;
  reasonText: string | null;
  actorId: string | null;
  actorName: string | null;
  createdAt: string;
}

export interface TestTaskSummary {
  myDraftAndReadyCount: number;
  myInProgressCount: number;
  myParticipantCount: number;
  blockedCount: number;
  overdueCount: number;
  dueSoonCount: number;
  recentTasks: TestTask[];
}

export interface TestTaskRequirementsResponse {
  warnings: Array<{
    requirementNo: string;
    requirementTitle: string;
    taskId: string;
    taskNo: string;
    taskTitle: string;
    ownerName: string;
    status: string;
  }>;
  task: TestTask;
}

export const testTasksApi = {
  list(
    projectId: string,
    params: {
      q?: string;
      versionId?: string;
      requirementId?: string;
      taskType?: string;
      status?: string;
      priority?: string;
      ownerId?: string;
      participantId?: string;
      isBlocked?: boolean;
      isOverdue?: boolean;
      sortBy?: string;
      sortOrder?: string;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<TestTaskListResponse> {
    const query = new URLSearchParams();
    if (params.q) query.append("q", params.q);
    if (params.versionId) query.append("versionId", params.versionId);
    if (params.requirementId) query.append("requirementId", params.requirementId);
    if (params.taskType) query.append("taskType", params.taskType);
    if (params.status) query.append("status", params.status);
    if (params.priority) query.append("priority", params.priority);
    if (params.ownerId) query.append("ownerId", params.ownerId);
    if (params.participantId) query.append("participantId", params.participantId);
    if (params.isBlocked !== undefined) query.append("isBlocked", String(params.isBlocked));
    if (params.isOverdue !== undefined) query.append("isOverdue", String(params.isOverdue));
    if (params.sortBy) query.append("sortBy", params.sortBy);
    if (params.sortOrder) query.append("sortOrder", params.sortOrder);
    if (params.limit !== undefined) query.append("limit", String(params.limit));
    if (params.offset !== undefined) query.append("offset", String(params.offset));

    const queryString = query.toString();
    const path = `/api/v1/projects/${projectId}/test-tasks${queryString ? "?" + queryString : ""}`;

    return apiClient.get(path, (data) => data as TestTaskListResponse);
  },

  get(projectId: string, taskId: string): Promise<TestTask> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}`,
      (data) => data as TestTask,
    );
  },

  create(projectId: string, payload: TestTaskCreatePayload, requestId = ""): Promise<TestTask> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/test-tasks${requestId ? "?request_id=" + requestId : ""}`,
      (data) => data as TestTask,
      payload,
    );
  },

  update(
    projectId: string,
    taskId: string,
    payload: TestTaskUpdatePayload,
    requestId = "",
  ): Promise<TestTask> {
    return apiClient.patch(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}${requestId ? "?request_id=" + requestId : ""}`,
      (data) => data as TestTask,
      payload,
    );
  },

  updateRequirements(
    projectId: string,
    taskId: string,
    payload: { requirementId: string | null },
    requestId = "",
  ): Promise<TestTaskRequirementsResponse> {
    return apiClient.put(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}/requirements${requestId ? "?request_id=" + requestId : ""}`,
      (data) => data as TestTaskRequirementsResponse,
      payload,
    );
  },

  updateParticipants(
    projectId: string,
    taskId: string,
    payload: { userIds: string[] },
    requestId = "",
  ): Promise<TestTask> {
    return apiClient.put(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}/participants${requestId ? "?request_id=" + requestId : ""}`,
      (data) => data as TestTask,
      payload,
    );
  },

  transition(
    projectId: string,
    taskId: string,
    payload: {
      targetStatus: string;
      reasonCode?: string | null;
      reasonText?: string | null;
      rowVersion: number;
    },
    requestId = "",
  ): Promise<TestTask> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}/transitions${requestId ? "?request_id=" + requestId : ""}`,
      (data) => data as TestTask,
      payload,
    );
  },

  listActivities(
    projectId: string,
    taskId: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<TestTaskActivity[]> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.append("limit", String(params.limit));
    if (params.offset !== undefined) query.append("offset", String(params.offset));

    const queryString = query.toString();
    const path = `/api/v1/projects/${projectId}/test-tasks/${taskId}/activities${queryString ? "?" + queryString : ""}`;
    return apiClient.get(path, (data) => data as TestTaskActivity[]);
  },

  listRequirements(projectId: string, taskId: string): Promise<any[]> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/test-tasks/${taskId}/requirements`,
      (data) => data as any[],
    );
  },

  mySummary(projectId: string): Promise<TestTaskSummary> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/test-tasks/my-summary`,
      (data) => data as TestTaskSummary,
    );
  },
};
