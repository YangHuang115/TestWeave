import { apiClient } from "../../shared/api/client";

export interface Version {
  id: string;
  key: string;
  name: string;
  description: string | null;
  status: "PLANNING" | "ACTIVE" | "TESTING" | "RELEASED" | "ARCHIVED";
  ownerId: string;
  plannedStartAt: string | null;
  plannedEndAt: string | null;
  rowVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface VersionListResponse {
  items: Version[];
  total: number;
}

export interface VersionCreatePayload {
  key: string;
  name: string;
  description?: string;
  owner_id: string;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
}

export interface VersionUpdatePayload {
  name: string;
  description?: string | null;
  owner_id: string;
  status: string;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  rowVersion: number;
}

export const versionsApi = {
  list(
    projectId: string,
    params: {
      name_or_key?: string;
      status?: string;
      owner_id?: string;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<VersionListResponse> {
    const query = new URLSearchParams();
    if (params.name_or_key) query.append("name_or_key", params.name_or_key);
    if (params.status) query.append("status", params.status);
    if (params.owner_id) query.append("owner_id", params.owner_id);
    if (params.limit !== undefined) query.append("limit", String(params.limit));
    if (params.offset !== undefined) query.append("offset", String(params.offset));

    const queryString = query.toString();
    const path = `/api/v1/projects/${projectId}/versions${queryString ? "?" + queryString : ""}`;

    return apiClient.get(path, (data) => data as VersionListResponse);
  },

  get(projectId: string, versionId: string): Promise<Version> {
    return apiClient.get(
      `/api/v1/projects/${projectId}/versions/${versionId}`,
      (data) => data as Version,
    );
  },

  create(projectId: string, payload: VersionCreatePayload): Promise<Version> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/versions`,
      (data) => data as Version,
      payload,
    );
  },

  update(projectId: string, versionId: string, payload: VersionUpdatePayload): Promise<Version> {
    return apiClient.patch(
      `/api/v1/projects/${projectId}/versions/${versionId}`,
      (data) => data as Version,
      payload,
    );
  },

  archive(projectId: string, versionId: string): Promise<Version> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/versions/${versionId}/archive`,
      (data) => data as Version,
    );
  },

  restore(projectId: string, versionId: string): Promise<Version> {
    return apiClient.post(
      `/api/v1/projects/${projectId}/versions/${versionId}/restore`,
      (data) => data as Version,
    );
  },
};
