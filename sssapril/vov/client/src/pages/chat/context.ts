import { createContext, useContext } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  CircleIcon, PlayCircleIcon, CheckCircleIcon,
  FileTextIcon, BookOpenIcon, LightbulbIcon, MapIcon,
} from 'lucide-react';
import type {
  GroupStatus, Resource, ResourceType, ProjectBundleMode, TaskListItem,
} from '../../types';
import type { TreeSelection, ProjectTreeNode } from '../../lib/projectContentTree';

// ── Exported types ──

export type MainMode = 'chat' | 'resource-view' | 'resource-create' | 'resource-edit' | 'project-details' | 'project-export';
export type RightTab = 'tasks' | 'members';

export type ResourceFormState = {
  title: string;
  content: string;
  type: ResourceType;
  is_required: boolean;
  tags: string;
};

// ── Shared constants ──

export const groupStatusConfig: Record<GroupStatus, { icon: LucideIcon; label: string; color: string; dot: string }> = {
  pending: { icon: CircleIcon, label: '待开始', color: 'text-foreground/40', dot: 'bg-foreground/30' },
  active: { icon: PlayCircleIcon, label: '进行中', color: 'text-foreground/60', dot: 'bg-foreground/60 animate-pulse' },
  completed: { icon: CheckCircleIcon, label: '已完成', color: 'text-foreground/80', dot: 'bg-foreground/80' },
};

export const resourceTypeConfig: Record<ResourceType, { icon: LucideIcon; label: string; color: string; chip: string }> = {
  note: { icon: FileTextIcon, label: '笔记', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
  reference: { icon: BookOpenIcon, label: '参考资料', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
  guideline: { icon: LightbulbIcon, label: '指南', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
  rule: { icon: FileTextIcon, label: '规则', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
  custom: { icon: FileTextIcon, label: '自定义', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
  map: { icon: MapIcon, label: '地图', color: 'text-foreground/60 bg-foreground/5', chip: 'border border-foreground/20 text-foreground/60' },
};

export const emptyResourceForm: ResourceFormState = {
  title: '',
  content: '',
  type: 'note',
  is_required: false,
  tags: '',
};

export const exportModes: Array<{ value: ProjectBundleMode; label: string }> = [
  { value: 'share', label: '分享包' },
  { value: 'template', label: '模板' },
  { value: 'backup', label: '备份' },
  { value: 'custom', label: '自定义' },
];

// ── Shared utility functions ──

export function formatResourceDate(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function parseResourceTags(raw: string) {
  return raw.split(/[,，\n]/).map(tag => tag.trim()).filter(Boolean);
}

export function resourceToForm(resource: Resource): ResourceFormState {
  return {
    title: resource.title,
    content: resource.content,
    type: resource.type,
    is_required: resource.is_required,
    tags: (resource.tags || []).join(', '),
  };
}

export function labelForCount(key: string) {
  const labels: Record<string, string> = {
    agents: 'Agent',
    skills: 'Skill',
    groups: '群聊',
    tasks: '任务',
    resources: '资料',
    deliverables: '交付物',
    messages: '聊天',
    memories: '记忆',
    tags: '标签',
  };
  return labels[key] || key;
}

// ── Context ──

export interface ChatPageContextValue {
  // Route params
  projectId: string;
  groupId: string;
  navigate: (path: string) => void;

  // Core data
  project: any;
  group: any;
  groupsData: any;
  projectAgentsData: any;
  projectResourcesData: any;
  skillsData: any;
  deliverablesData: any;

  // Main mode
  mainMode: MainMode;
  setMainMode: (mode: MainMode) => void;

  // Left sidebar
  leftTab: 'groups' | 'resources';
  setLeftTab: (tab: 'groups' | 'resources') => void;
  sortedGroups: any[];
  activeGroupId: string;
  setActiveGroupId: (id: string) => void;
  creatingGroup: boolean;
  setCreatingGroup: (v: boolean) => void;

  // Right sidebar
  rightTab: RightTab;
  setRightTab: (tab: RightTab) => void;

  // Chat state
  inputText: string;
  setInputText: (v: string) => void;
  isSending: boolean;
  setIsSending: React.Dispatch<React.SetStateAction<boolean>>;
  isStreaming: boolean;
  // 当前正在被 attach 追踪的 chain (resume 状态). 用于 ChatPanel 决定
  // 哪些 taskChainView 应该被标 liveStream=true, 让 ChainBlock 显示流式光标
  streamingChainId: string | null;
  streamingPacketId: string | null;
  handleStopStream: () => void;
  activeReplyChain: any;
  taskChainViews: any[];
  chainViewCache: any;
  chainsLoading: boolean;
  handleTaskClick: (task: any) => void;
  handleLoadSubChain: (chainId: string) => void;
  /** 刷新群链视图 (任务变更后调用, 让内联 task chain 块即时更新) */
  refreshChains: () => void;
  // v2 P2+: 用户从侧边栏点击 task 后, 对应 chain 强制展开 + 滚动到视口
  // ChainBlock 读这个集合决定 forceExpanded, ChatPanel 监听它做滚动
  forceExpandedChainIds: Set<string>;
  members: any[];
  agentList: Array<{ id: string; name: string; avatar?: string }>;
  hasMessages: boolean;
  chatStreamSend: (text: string, agentId?: string, setIsSending?: React.Dispatch<React.SetStateAction<boolean>>) => Promise<void>;

  // Scroll
  scrollContainerRef: React.RefObject<HTMLDivElement>;
  messagesEndRef: React.RefObject<HTMLDivElement>;
  showScrollBtns: boolean;
  scrollToTop: () => void;
  scrollToBottom: () => void;
  scrollToPrevMsg: () => void;
  scrollToNextMsg: () => void;
  handleScroll: () => void;

  // Resource
  selectedResourceId: string | null;
  setSelectedResourceId: (id: string | null) => void;
  selectedResource: Resource | null;
  resourceQuery: string;
  setResourceQuery: (v: string) => void;
  resourceTypeFilter: ResourceType | 'all';
  setResourceTypeFilter: (v: ResourceType | 'all') => void;
  filteredResources: Resource[];
  projectResources: Resource[];
  // 当前激活群(group_id=activeGroupId)的群级资料(走 /groups/{id}/resources).
  // 与 projectResources 不重叠: 后者只含 group_id IS NULL 的全局资料.
  groupResources: Resource[];
  // 当前激活群的名称, LeftSidebar 用作"群内资料"分组标题.
  activeGroupName: string;
  openResource: (resource: Resource) => void;
  startCreateResource: () => void;
  startEditResource: () => void;

  // Resource form (for ResourcePanel)
  resourceForm: ResourceFormState;
  setResourceForm: React.Dispatch<React.SetStateAction<ResourceFormState>>;
  resourceSaving: boolean;
  cancelResourceForm: () => void;
  handleSaveResource: () => Promise<void>;
  resourceHeadings: Array<{ id: string; level: number; text: string }>;
  deletingResource: Resource | null;
  setDeletingResource: (r: Resource | null) => void;

  // Agent popup
  chatSelectedAgent: any;
  setChatSelectedAgent: (agent: any) => void;

  // Modals
  editingGroup: boolean;
  setEditingGroup: (v: boolean) => void;

  // Textarea ref (for mention system in ChatPanel)
  textareaRef: React.RefObject<HTMLTextAreaElement>;

  // Project details/export
  previewBundle: any;
  exportBundle: any;
  projectBundleSelection: any;
  projectTreeNodes: ProjectTreeNode[];
  projectTreeExpanded: Record<string, boolean>;
  setProjectTreeExpanded: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  projectTreeSelection: TreeSelection;
  setProjectTreeSelection: React.Dispatch<React.SetStateAction<TreeSelection>>;
  exportMode: ProjectBundleMode;
  setExportMode: (mode: ProjectBundleMode) => void;
  handleProjectExport: () => void;
  handleProjectExportMode: (mode: ProjectBundleMode) => void;
  handleViewDeliverable: (delivId: string) => void;
}

export const ChatPageContext = createContext<ChatPageContextValue | null>(null);

export function useChatPage(): ChatPageContextValue {
  const ctx = useContext(ChatPageContext);
  if (!ctx) throw new Error('useChatPage must be used within ChatPageContext.Provider');
  return ctx;
}
