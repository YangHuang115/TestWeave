import { apiClient } from "../../shared/api/client";

export interface CaseModuleNode {
  id: string;
  projectId: string;
  parentId: string | null;
  name: string;
  description: string | null;
  sortOrder: number;
  children: CaseModuleNode[];
}

export interface TestCaseStepItem {
  id?: string;
  stepOrder?: number;
  action: string;
  expectedResult: string;
  note?: string | null;
}

export interface TestCaseItem {
  id: string;
  projectId: string;
  caseNo: string;
  title: string;
  precondition: string | null;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  caseType: string;
  tagsJson: string[];
  testDataNote: string | null;
  note: string | null;
  sourceTaskId: string | null;
  currentRevisionId: string | null;
  rowVersion: number;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
  steps?: TestCaseStepItem[];
  moduleIds?: string[];
}

export interface TestCaseEditSession {
  id: string;
  caseId: string;
  actorId: string;
  baseRevisionId: string | null;
  baseRowVersion: number;
  status: "OPEN" | "FINALIZED" | "ABANDONED";
  dirtyFields: Record<string, unknown>;
  startedAt: string;
  lastActivityAt: string;
  finalizedAt: string | null;
}

export interface TestCaseRevision {
  id: string;
  caseId: string;
  revisionNo: number;
  snapshot: Record<string, unknown>;
  snapshotHash: string;
  changeSummary: Record<string, unknown>;
  editSessionId: string | null;
  createdBy: string;
  createdAt: string;
}

// 模块树 API
export async function getModuleTree(projectId: string): Promise<CaseModuleNode[]> {
  const res = await apiClient.get<CaseModuleNode[]>(`/api/v1/projects/${projectId}/case-modules/tree`);
  return res.data;
}

export async function createModule(
  projectId: string,
  payload: { name: string; parentId?: string | null; description?: string | null; sortOrder?: number }
): Promise<CaseModuleNode> {
  const res = await apiClient.post<CaseModuleNode>(`/api/v1/projects/${projectId}/case-modules`, payload);
  return res.data;
}

export async function updateModule(
  projectId: string,
  moduleId: string,
  payload: { name: string; description?: string | null; sortOrder?: number }
): Promise<CaseModuleNode> {
  const res = await apiClient.put<CaseModuleNode>(
    `/api/v1/projects/${projectId}/case-modules/${moduleId}`,
    payload
  );
  return res.data;
}

export async function moveModule(
  projectId: string,
  moduleId: string,
  targetParentId: string | null
): Promise<CaseModuleNode> {
  const res = await apiClient.put<CaseModuleNode>(
    `/api/v1/projects/${projectId}/case-modules/${moduleId}/move`,
    { targetParentId }
  );
  return res.data;
}

export async function archiveModule(projectId: string, moduleId: string): Promise<CaseModuleNode> {
  const res = await apiClient.post<CaseModuleNode>(
    `/api/v1/projects/${projectId}/case-modules/${moduleId}/archive`
  );
  return res.data;
}

// 用例及编辑会话 API
export async function getTestCases(
  projectId: string,
  params?: { moduleId?: string | null; keyword?: string; priority?: string; caseType?: string }
): Promise<TestCaseItem[]> {
  const query = new URLSearchParams();
  if (params?.moduleId) query.append("moduleId", params.moduleId);
  if (params?.keyword) query.append("keyword", params.keyword);
  if (params?.priority) query.append("priority", params.priority);
  if (params?.caseType) query.append("caseType", params.caseType);

  const url = `/api/v1/projects/${projectId}/test-cases${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await apiClient.get<TestCaseItem[]>(url);
  return res.data;
}

export async function getTestCaseDetail(projectId: string, caseId: string): Promise<TestCaseItem> {
  const res = await apiClient.get<TestCaseItem>(`/api/v1/projects/${projectId}/test-cases/${caseId}`);
  return res.data;
}

export async function createTestCase(
  projectId: string,
  payload: {
    title: string;
    precondition?: string | null;
    priority?: string;
    caseType?: string;
    tagsJson?: string[];
    testDataNote?: string | null;
    note?: string | null;
    steps?: { action: string; expectedResult: string; note?: string | null }[];
    sourceTaskId?: string | null;
    moduleIds?: string[];
  }
): Promise<TestCaseItem> {
  const res = await apiClient.post<TestCaseItem>(`/api/v1/projects/${projectId}/test-cases`, payload);
  return res.data;
}

export async function startEditSession(projectId: string, caseId: string): Promise<TestCaseEditSession> {
  const res = await apiClient.post<TestCaseEditSession>(
    `/api/v1/projects/${projectId}/test-cases/${caseId}/edit-sessions`
  );
  return res.data;
}

export async function updateSessionDraft(
  projectId: string,
  caseId: string,
  sessionId: string,
  dirtyFields: Record<string, unknown>
): Promise<TestCaseEditSession> {
  const res = await apiClient.put<TestCaseEditSession>(
    `/api/v1/projects/${projectId}/test-cases/${caseId}/edit-sessions/${sessionId}/draft`,
    { dirtyFields }
  );
  return res.data;
}

export async function finalizeEditSession(
  projectId: string,
  caseId: string,
  sessionId: string,
  changeSummary?: Record<string, unknown>
): Promise<TestCaseRevision> {
  const res = await apiClient.post<TestCaseRevision>(
    `/api/v1/projects/${projectId}/test-cases/${caseId}/edit-sessions/${sessionId}/finalize`,
    { changeSummary: changeSummary || {} }
  );
  return res.data;
}

export async function abandonEditSession(
  projectId: string,
  caseId: string,
  sessionId: string
): Promise<TestCaseEditSession> {
  const res = await apiClient.post<TestCaseEditSession>(
    `/api/v1/projects/${projectId}/test-cases/${caseId}/edit-sessions/${sessionId}/abandon`
  );
  return res.data;
}

export async function getTestCaseRevisions(projectId: string, caseId: string): Promise<TestCaseRevision[]> {
  const res = await apiClient.get<TestCaseRevision[]>(
    `/api/v1/projects/{projectId}/test-cases/${caseId}/revisions`.replace("{projectId}", projectId)
  );
  return res.data;
}

export interface TestCaseMindmap {
  id: string;
  projectId: string;
  taskId: string;
  title: string;
  data: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

export async function getMindmap(projectId: string, taskId: string): Promise<TestCaseMindmap> {
  return apiClient.get<TestCaseMindmap>(
    `/api/v1/projects/${projectId}/test-tasks/${taskId}/mindmap`,
    (data) => data as TestCaseMindmap
  );
}

export async function saveMindmap(
  projectId: string,
  taskId: string,
  payload: { title: string; data: Record<string, any> }
): Promise<TestCaseMindmap> {
  return apiClient.put<TestCaseMindmap>(
    `/api/v1/projects/${projectId}/test-tasks/${taskId}/mindmap`,
    (data) => data as TestCaseMindmap,
    payload
  );
}

export async function syncMindmapToCases(
  projectId: string,
  taskId: string
): Promise<{ status: string; syncedCount: number }> {
  return apiClient.post<{ status: string; syncedCount: number }>(
    `/api/v1/projects/${projectId}/test-tasks/${taskId}/mindmap/sync`,
    (data) => data as { status: string; syncedCount: number },
    {}
  );
}

