import { apiClient } from '@/shared/api/client'

export interface WorkbenchSummary {
  remaining_requirements_count: number
  my_todos_count: number
  in_progress_tasks_count: number
  waiting_human_count: number
  generated_at: string
}

export interface WorkbenchTodoItem {
  id: string
  type: string
  title: string
  version_id?: string
  version_name?: string
  task_id?: string
  task_title?: string
  priority: 'HIGH' | 'MEDIUM' | 'LOW'
  due_at?: string
  created_at: string
  urgency: 'BLOCKED' | 'OVERDUE' | 'NORMAL'
  sub_item_count: number
  target_type: string
  target_id: string
  target_route: string
}

export interface WorkbenchInProgressTask {
  id: string
  task_no: string
  title: string
  version_id?: string
  version_name?: string
  role: 'OWNER' | 'PARTICIPANT'
  status: string
  progress_percent?: number
  is_blocked: boolean
  updated_at: string
}

export interface WorkbenchAgentRunItem {
  id: string
  capability_id?: string
  capability_name?: string
  task_id?: string
  task_title?: string
  status: string
  current_stage?: string
  started_at?: string
  updated_at: string
  error_summary?: string
  executable_actions: string[]
}

export interface WorkbenchRemainingRequirement {
  id: string
  requirement_no: string
  title: string
  priority: string
  status: string
  version_name?: string
  updated_at: string
  target_route: string
}

export interface WorkbenchRecentVisit {
  id: string
  resource_type: string
  resource_id: string
  title: string
  visited_at: string
  target_route: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

const API_BASE = '/api/v1'

export const workbenchApi = {
  getSummary(projectId: string, signal?: AbortSignal): Promise<WorkbenchSummary> {
    return apiClient.get<WorkbenchSummary>(
      `${API_BASE}/projects/${projectId}/workbench/summary`,
      undefined,
      { signal }
    )
  },

  getTodos(
    projectId: string,
    params?: {
      type?: string
      priority?: string
      is_overdue?: boolean
      limit?: number
      offset?: number
    },
    signal?: AbortSignal
  ): Promise<PaginatedResponse<WorkbenchTodoItem>> {
    const query = new URLSearchParams()
    if (params?.type) query.append('type', params.type)
    if (params?.priority) query.append('priority', params.priority)
    if (params?.is_overdue !== undefined) query.append('is_overdue', String(params.is_overdue))
    if (params?.limit !== undefined) query.append('limit', String(params.limit))
    if (params?.offset !== undefined) query.append('offset', String(params.offset))
    const qStr = query.toString()
    const path = `${API_BASE}/projects/${projectId}/workbench/todos${qStr ? '?' + qStr : ''}`
    return apiClient.get<PaginatedResponse<WorkbenchTodoItem>>(path, undefined, { signal })
  },

  getInProgressTasks(
    projectId: string,
    params?: { limit?: number; offset?: number },
    signal?: AbortSignal
  ): Promise<PaginatedResponse<WorkbenchInProgressTask>> {
    const query = new URLSearchParams()
    if (params?.limit !== undefined) query.append('limit', String(params.limit))
    if (params?.offset !== undefined) query.append('offset', String(params.offset))
    const qStr = query.toString()
    const path = `${API_BASE}/projects/${projectId}/workbench/in-progress-tasks${qStr ? '?' + qStr : ''}`
    return apiClient.get<PaginatedResponse<WorkbenchInProgressTask>>(path, undefined, { signal })
  },

  getAgentRuns(
    projectId: string,
    params?: { status?: string; limit?: number; offset?: number },
    signal?: AbortSignal
  ): Promise<PaginatedResponse<WorkbenchAgentRunItem>> {
    const query = new URLSearchParams()
    if (params?.status) query.append('status', params.status)
    if (params?.limit !== undefined) query.append('limit', String(params.limit))
    if (params?.offset !== undefined) query.append('offset', String(params.offset))
    const qStr = query.toString()
    const path = `${API_BASE}/projects/${projectId}/workbench/agent-runs${qStr ? '?' + qStr : ''}`
    return apiClient.get<PaginatedResponse<WorkbenchAgentRunItem>>(path, undefined, { signal })
  },

  getRemainingRequirements(
    projectId: string,
    params?: { limit?: number; offset?: number },
    signal?: AbortSignal
  ): Promise<PaginatedResponse<WorkbenchRemainingRequirement>> {
    const query = new URLSearchParams()
    if (params?.limit !== undefined) query.append('limit', String(params.limit))
    if (params?.offset !== undefined) query.append('offset', String(params.offset))
    const qStr = query.toString()
    const path = `${API_BASE}/projects/${projectId}/workbench/remaining-requirements${qStr ? '?' + qStr : ''}`
    return apiClient.get<PaginatedResponse<WorkbenchRemainingRequirement>>(path, undefined, { signal })
  },

  getRecentVisits(
    projectId: string,
    params?: { limit?: number; offset?: number },
    signal?: AbortSignal
  ): Promise<PaginatedResponse<WorkbenchRecentVisit>> {
    const query = new URLSearchParams()
    if (params?.limit !== undefined) query.append('limit', String(params.limit))
    if (params?.offset !== undefined) query.append('offset', String(params.offset))
    const qStr = query.toString()
    const path = `${API_BASE}/projects/${projectId}/workbench/recent-visits${qStr ? '?' + qStr : ''}`
    return apiClient.get<PaginatedResponse<WorkbenchRecentVisit>>(path, undefined, { signal })
  },

  recordRecentVisit(
    projectId: string,
    payload: { resource_type: string; resource_id: string }
  ): Promise<WorkbenchRecentVisit> {
    return apiClient.post<WorkbenchRecentVisit>(
      `${API_BASE}/projects/${projectId}/workbench/recent-visits`,
      undefined,
      payload
    )
  }
}
