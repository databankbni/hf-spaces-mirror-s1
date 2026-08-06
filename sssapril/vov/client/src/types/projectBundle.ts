import type { ResourceType } from './common';

export type ProjectBundleMode = 'share' | 'template' | 'backup' | 'custom';

export interface ProjectBundleItemSelection {
  include: boolean;
  ids: string[];
  group_ids?: string[];
  task_ids?: string[];
}

export type ProjectBundleSelectable = boolean | ProjectBundleItemSelection;

export interface ProjectBundleResourceSelection extends ProjectBundleItemSelection {
  types: ResourceType[];
  required_only: boolean;
}

export interface ProjectBundleSelection {
  mode: ProjectBundleMode;
  project_meta: boolean;
  agents: ProjectBundleSelectable;
  skills: ProjectBundleSelectable;
  groups: ProjectBundleSelectable;
  tasks: ProjectBundleSelectable;
  resources: ProjectBundleResourceSelection;
  deliverables: ProjectBundleSelectable;
  messages: ProjectBundleSelectable;
  memories: ProjectBundleSelectable;
  tags: ProjectBundleSelectable;
  options?: Record<string, unknown>;
}

export interface ProjectBundlePreview {
  schema_version: string;
  bundle_type: ProjectBundleMode;
  selection: ProjectBundleSelection;
  project: {
    id: string;
    name: string;
    description: string | null;
  } | null;
  counts: Record<string, number>;
  excluded: Record<string, number>;
  warnings: string[];
  files: Record<string, string[]>;
}
