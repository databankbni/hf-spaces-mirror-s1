import { apiClient } from './client';
import type { ApiResponse, ProjectBundlePreview, ProjectBundleSelection } from '../types';

export const projectBundleApi = {
  async preview(projectId: string, selection: ProjectBundleSelection): Promise<ApiResponse<ProjectBundlePreview>> {
    return apiClient.post<ProjectBundlePreview>(`/projects/${projectId}/export/preview`, selection);
  },

  async download(projectId: string, selection: ProjectBundleSelection, filename: string): Promise<void> {
    return apiClient.postDownload(`/projects/${projectId}/export/bundle`, selection, filename);
  },
};
