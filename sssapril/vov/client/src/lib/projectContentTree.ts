import type {
  DeliverableListItem,
  GroupListItem,
  Project,
  ProjectBundleMode,
  ProjectBundleSelection,
  ProjectBundleSelectable,
  ProjectListItem,
  ProjectAgent,
  Resource,
  ResourceType,
  Skill,
  TaskListItem,
} from '../types';

type ProjectLike = Project | ProjectListItem;

export type ProjectTreeNodeKind =
  | 'project'
  | 'section'
  | 'agent'
  | 'skill'
  | 'group'
  | 'task'
  | 'resource-type'
  | 'resource'
  | 'deliverable'
  | 'messages';

export interface ProjectTreeNode {
  id: string;
  kind: ProjectTreeNodeKind;
  label: string;
  description?: string | null;
  badge?: string;
  exportKey?: keyof Omit<ProjectBundleSelection, 'mode' | 'options'>;
  entityId?: string;
  children?: ProjectTreeNode[];
}

export type TreeSelection = Record<string, boolean>;

export interface BuildProjectTreeInput {
  project: ProjectLike;
  groups: GroupListItem[];
  agents: ProjectAgent[];
  skills: Skill[];
  resources: Resource[];
  tasks: TaskListItem[];
  deliverables: DeliverableListItem[];
}

const resourceTypeLabels: Record<ResourceType, string> = {
  note: '笔记',
  reference: '参考资料',
  guideline: '指南',
  rule: '规则',
  custom: '自定义',
  map: '地图',
};

export function buildProjectContentTree(input: BuildProjectTreeInput): ProjectTreeNode[] {
  const agentSkillIds = new Set(input.agents.flatMap(item => item.agent?.skills?.map(skill => skill.id) || []));
  const relatedSkills = input.skills.filter(skill => agentSkillIds.has(skill.id));

  return [
    {
      id: `project:${input.project.id}`,
      kind: 'project',
      label: input.project.name,
      description: input.project.description,
      exportKey: 'project_meta',
      entityId: input.project.id,
      children: [
        {
          id: 'section:agents',
          kind: 'section',
          label: 'Agent',
          badge: `${input.agents.length}`,
          exportKey: 'agents',
          children: input.agents.map(projectAgent => ({
            id: `agent:${projectAgent.id}`,
            kind: 'agent',
            label: projectAgent.agent?.name || 'Unknown Agent',
            description: projectAgent.agent?.description,
            // v2 P3: 删除 role 字段, agent 标签由 description/capabilities 表达
            exportKey: 'agents',
            entityId: projectAgent.id,
            children: (projectAgent.agent?.skills || []).map(skill => ({
              id: `agent:${projectAgent.id}:skill:${skill.id}`,
              kind: 'skill',
              label: skill.name,
              description: skill.description,
              badge: skill.skill_type,
              exportKey: 'skills',
              entityId: skill.id,
            })),
          })),
        },
        {
          id: 'section:skills',
          kind: 'section',
          label: 'Skill',
          badge: `${relatedSkills.length}`,
          exportKey: 'skills',
          children: relatedSkills.map(skill => ({
            id: `skill:${skill.id}`,
            kind: 'skill',
            label: skill.name,
            description: skill.description,
            badge: skill.skill_type,
            exportKey: 'skills',
            entityId: skill.id,
          })),
        },
        {
          id: 'section:groups',
          kind: 'section',
          label: '群聊',
          badge: `${input.groups.length}`,
          exportKey: 'groups',
          children: input.groups.map(group => ({
            id: `group:${group.id}`,
            kind: 'group',
            label: group.name,
            description: group.description,
            badge: `${group.task_count || 0} 任务`,
            exportKey: 'groups',
            entityId: group.id,
            children: [
              ...input.tasks.filter(task => task.group_id === group.id).map(task => ({
                id: `task:${task.id}`,
                kind: 'task' as const,
                label: task.title,
                description: task.description,
                badge: task.status,
                exportKey: 'tasks' as const,
                entityId: task.id,
              })),
              {
                id: `messages:group:${group.id}`,
                kind: 'messages',
                label: '聊天记录',
                badge: `${group.message_count || 0}`,
                exportKey: 'messages',
                entityId: group.id,
              },
            ],
          })),
        },
        {
          id: 'section:resources',
          kind: 'section',
          label: '资料库',
          badge: `${input.resources.length}`,
          exportKey: 'resources',
          children: buildResourceNodes(input.resources),
        },
        {
          id: 'section:deliverables',
          kind: 'section',
          label: '交付物',
          badge: `${input.deliverables.length}`,
          exportKey: 'deliverables',
          children: input.deliverables.map(deliverable => ({
            id: `deliverable:${deliverable.id}`,
            kind: 'deliverable',
            label: deliverable.title,
            badge: deliverable.type || deliverable.scope,
            exportKey: 'deliverables',
            entityId: deliverable.id,
          })),
        },
      ],
    },
  ];
}

function buildResourceNodes(resources: Resource[]): ProjectTreeNode[] {
  return (Object.entries(resourceTypeLabels) as Array<[ResourceType, string]>).map(([type, label]) => {
    const items = resources.filter(resource => resource.type === type);
    return {
      id: `resource-type:${type}`,
      kind: 'resource-type',
      label,
      badge: `${items.length}`,
      exportKey: 'resources',
      entityId: type,
      children: items.map(resource => ({
        id: `resource:${resource.id}`,
        kind: 'resource',
        label: resource.title,
        description: resource.content.slice(0, 120),
        badge: resource.is_required ? '必读' : undefined,
        exportKey: 'resources',
        entityId: resource.id,
      })),
    };
  });
}

export function collectNodeIds(nodes: ProjectTreeNode[]): string[] {
  return nodes.flatMap(node => [node.id, ...collectNodeIds(node.children || [])]);
}

export function applyExportPreset(nodes: ProjectTreeNode[], mode: ProjectBundleMode): TreeSelection {
  const selection: TreeSelection = {};
  const excluded = new Set<ProjectTreeNodeKind>(
    mode === 'backup' ? [] : ['deliverable', 'messages'],
  );

  const visit = (node: ProjectTreeNode) => {
    selection[node.id] = !excluded.has(node.kind);
    node.children?.forEach(visit);
  };
  nodes.forEach(visit);
  return selection;
}

export function toggleTreeNode(nodes: ProjectTreeNode[], selection: TreeSelection, nodeId: string): TreeSelection {
  const node = findNode(nodes, nodeId);
  if (!node) return selection;

  const next = { ...selection };
  const target = !isNodeChecked(node, selection);
  collectNodeIds([node]).forEach(id => {
    next[id] = target;
  });
  return next;
}

export function getNodeSelectionState(node: ProjectTreeNode, selection: TreeSelection): 'checked' | 'partial' | 'unchecked' {
  const ids = collectNodeIds([node]);
  const checkedCount = ids.filter(id => selection[id]).length;
  if (checkedCount === 0) return 'unchecked';
  if (checkedCount === ids.length) return 'checked';
  return 'partial';
}

export function treeSelectionToBundleSelection(nodes: ProjectTreeNode[], selection: TreeSelection, mode: ProjectBundleMode): ProjectBundleSelection {
  const ids = {
    agents: new Set<string>(),
    skills: new Set<string>(),
    groups: new Set<string>(),
    tasks: new Set<string>(),
    resources: new Set<string>(),
    resourceTypes: new Set<ResourceType>(),
    deliverables: new Set<string>(),
    messageGroups: new Set<string>(),
  };

  const visit = (node: ProjectTreeNode) => {
    if (!selection[node.id]) {
      node.children?.forEach(visit);
      return;
    }
    if (node.kind === 'agent' && node.entityId) ids.agents.add(node.entityId);
    if (node.kind === 'skill' && node.entityId) ids.skills.add(node.entityId);
    if (node.kind === 'group' && node.entityId) ids.groups.add(node.entityId);
    if (node.kind === 'task' && node.entityId) ids.tasks.add(node.entityId);
    if (node.kind === 'resource' && node.entityId) ids.resources.add(node.entityId);
    if (node.kind === 'resource-type' && node.entityId) ids.resourceTypes.add(node.entityId as ResourceType);
    if (node.kind === 'deliverable' && node.entityId) ids.deliverables.add(node.entityId);
    if (node.kind === 'messages' && node.entityId) ids.messageGroups.add(node.entityId);
    node.children?.forEach(visit);
  };
  nodes.forEach(visit);

  return {
    mode,
    project_meta: !!selection[nodes[0]?.id],
    agents: itemSelection(ids.agents),
    skills: itemSelection(ids.skills),
    groups: itemSelection(ids.groups),
    tasks: itemSelection(ids.tasks),
    resources: {
      include: ids.resources.size > 0 || ids.resourceTypes.size > 0 || !!selection['section:resources'],
      ids: [...ids.resources],
      types: [...ids.resourceTypes],
      required_only: false,
    },
    deliverables: itemSelection(ids.deliverables),
    messages: {
      include: ids.messageGroups.size > 0 || !!selection['section:groups'],
      ids: [],
      group_ids: [...ids.messageGroups],
      task_ids: [],
    },
    memories: false,
    tags: true,
  };
}

function itemSelection(ids: Set<string>): ProjectBundleSelectable {
  return {
    include: ids.size > 0,
    ids: [...ids],
  };
}

function findNode(nodes: ProjectTreeNode[], nodeId: string): ProjectTreeNode | null {
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const found = findNode(node.children || [], nodeId);
    if (found) return found;
  }
  return null;
}

function isNodeChecked(node: ProjectTreeNode, selection: TreeSelection) {
  return collectNodeIds([node]).every(id => selection[id]);
}
