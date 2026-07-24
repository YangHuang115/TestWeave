import { httpClient } from '@/shared/api/httpClient';

export interface EvaluationSet {
  id: string;
  project_id: string | null;
  scope_type: string;
  set_key: string;
  name: string;
  description: string | null;
  current_revision_id: string | null;
}

export interface CaseRecommendation {
  id: string;
  source_type: string;
  source_id: string;
  suggested_inputs: any;
  status: string;
  created_at: string;
}

export interface OptimizationSuggestion {
  id: string;
  suggestion_type: string;
  title: string;
  description: string;
  evidence_count: number;
  suggested_action_area: string;
  status: string;
  created_at: string;
}

export interface WorkspacePackage {
  id: string;
  package_type: string;
  package_hash: string;
  status: string;
  evidence_manifest: any;
}

export interface CapabilityDeployment {
  id: string;
  capability_id: string;
  stable_version_id: string;
  canary_version_id: string | null;
  canary_basis_points: number;
  deployment_revision: number;
  status: string;
}

export interface ReleaseRequest {
  id: string;
  status: string;
  blocking_checks: any;
  advisories: any;
  request_fingerprint: string;
}

export const aiEvaluationsApi = {
  async listEvaluationSets(projectId: string): Promise<EvaluationSet[]> {
    const resp = await httpClient.get<EvaluationSet[]>(`/api/v1/projects/${projectId}/evaluation-sets`);
    return resp.data;
  },

  async createEvaluationSet(projectId: string, data: { set_key: string; name: string; description?: string }): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/${projectId}/evaluation-sets`, data);
    return resp.data;
  },

  async listRecommendations(projectId: string): Promise<CaseRecommendation[]> {
    const resp = await httpClient.get<CaseRecommendation[]>(`/api/v1/projects/${projectId}/case-recommendations`);
    return resp.data;
  },

  async acceptRecommendation(
    projectId: string,
    id: string,
    data: { case_name: string; redacted_inputs: any; declarative_assertions: any[] }
  ): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/${projectId}/case-recommendations/${id}/accept`, data);
    return resp.data;
  },

  async listOptimizationSuggestions(projectId: string): Promise<OptimizationSuggestion[]> {
    const resp = await httpClient.get<OptimizationSuggestion[]>(`/api/v1/projects/${projectId}/optimization-suggestions`);
    return resp.data;
  },

  async createWorkspacePackage(
    projectId: string,
    data: { capability_id: string; package_type: string; suggestion_ids?: string[] }
  ): Promise<WorkspacePackage> {
    const resp = await httpClient.post<WorkspacePackage>(`/api/v1/projects/${projectId}/workspace-packages`, data);
    return resp.data;
  },

  async getCapabilityDeployment(projectId: string, capabilityId: string): Promise<CapabilityDeployment> {
    const resp = await httpClient.get<CapabilityDeployment>(`/api/v1/projects/${projectId}/capabilities/${capabilityId}/deployment`);
    return resp.data;
  },

  async createReleaseRequest(
    projectId: string,
    capabilityId: string,
    data: { candidate_version_id: string; reason?: string }
  ): Promise<ReleaseRequest> {
    const resp = await httpClient.post<ReleaseRequest>(`/api/v1/projects/${projectId}/capabilities/${capabilityId}/release-requests`, data);
    return resp.data;
  },

  async startCanary(
    projectId: string,
    capabilityId: string,
    data: { release_request_id: string; canary_basis_points: number; reason: string }
  ): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/${projectId}/capabilities/${capabilityId}/deployments/start-canary`, data);
    return resp.data;
  },

  async adjustCanary(
    projectId: string,
    capabilityId: string,
    data: { canary_basis_points: number; expected_deployment_revision: number; reason: string }
  ): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/{projectId}/capabilities/{capabilityId}/deployments/adjust-canary`, data);
    return resp.data;
  },

  async promote(
    projectId: string,
    capabilityId: string,
    data: { expected_deployment_revision: number; reason: string }
  ): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/${projectId}/capabilities/${capabilityId}/deployments/promote`, data);
    return resp.data;
  },

  async rollback(
    projectId: string,
    capabilityId: string,
    data: { target_version_id: string; expected_deployment_revision: number; reason: string }
  ): Promise<any> {
    const resp = await httpClient.post(`/api/v1/projects/${projectId}/capabilities/${capabilityId}/deployments/rollback`, data);
    return resp.data;
  },
};
