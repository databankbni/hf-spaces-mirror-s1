import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { toast } from 'sonner';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { extractMarkdownHeadings } from '../components/markdown/MarkdownRenderer';
import ConfirmDialog from '../components/ConfirmDialog';
import AgentCard from '../components/AgentCard';
import EditGroupModal from '../components/EditGroupModal';
import CreateGroupModal from '../components/CreateGroupModal';
import { applyExportPreset, buildProjectContentTree, treeSelectionToBundleSelection, type TreeSelection } from '../lib/projectContentTree';
import { useAppStore } from '../store/appStore';
import { useProject } from '../hooks/useProjects';
import { useGroups, useGroup } from '../hooks/useGroups';
import { useProjectAgents } from '../hooks/useAgents';
import { useDeliverablesByProject } from '../hooks/useDeliverables';
import { useSkills } from '../hooks/useSkills';
import { usePreviewProjectBundle, useExportProjectBundle } from '../hooks/useProjectBundle';
import { useProjectResources, useGroupResources, useCreateResource, useUpdateResource, useDeleteResource } from '../hooks/useResources';
import { useChatStream } from '../hooks/useChatStream';
import { useChainViews } from '../hooks/useChainViews';
import { useWebSocket } from '../hooks/useWebSocket';
import { groupKeys } from '../hooks/useGroups';
import type { Resource, ResourceType, ProjectBundleMode, TaskListItem } from '../types';
import type { WsServerMessage } from '../types/message';
import {
  ChatPageContext, emptyResourceForm, parseResourceTags,
  type ChatPageContextValue, type MainMode, type RightTab, type ResourceFormState,
} from './chat/context';

import ChatTopBar from './chat/ChatTopBar';
import LeftSidebar from './chat/LeftSidebar';
import ChatPanel from './chat/ChatPanel';
import RightSidebar from './chat/RightSidebar';
import ProjectDetailsPanel from './chat/ProjectDetailsPanel';

/**
 * Chat stream 相关的 WebSocket 事件类型
 *
 * 这些事件由后端 StreamPushPlugin / chat_service 通过 ws_manager.broadcast 推送,
 * 前端收到后交给 useChatStream.handleStreamEvent 处理。
 */
const STREAM_WS_TYPES = new Set<string>([
  'token',
  'tool_call',
  'tool_result',
  'chain_start',
  'chain_end',
  'done',
  'error',
  'user_message',
]);

export default function ChatPage() {
  const navigate = useNavigate();
  const { projectId, groupId } = useParams<{ projectId: string; groupId: string }>();
  const { activeGroupId, setActiveGroupId } = useAppStore();
  const queryClient = useQueryClient();

  // ── Data hooks ──
  const { data: project, isLoading: projectLoading } = useProject(projectId || '');
  const { data: groupsData } = useGroups(projectId || '');
  const { data: group, isLoading: groupLoading } = useGroup(groupId || activeGroupId || '');
  const { data: projectAgentsData } = useProjectAgents(projectId || '');
  const { data: projectResourcesData } = useProjectResources(projectId || '');
  const { data: groupResourcesData } = useGroupResources(groupId || activeGroupId || '');
  const { data: skillsData } = useSkills();
  const { data: deliverablesData } = useDeliverablesByProject(projectId || '');
  const previewBundle = usePreviewProjectBundle();
  const exportBundle = useExportProjectBundle();
  const createResource = useCreateResource();
  const updateResource = useUpdateResource();
  const deleteResource = useDeleteResource();

  const groups = groupsData?.items || [];
  const sortedGroups = [...groups].sort((a, b) => a.order_index - b.order_index);
  const projectResources = projectResourcesData?.items || [];
  const groupResources = groupResourcesData?.items || [];
  const activeGroupName = group?.name || '';
  // 全局资料 + 当前群的群内资料 (互不重叠, 后端接口已分组, 这里简单拼接即可)
  // 直接依赖 queryData 引用, 避免 `data?.items || []` 每次渲染产生新引用触发 useMemo 重算
  const allResources = useMemo(
    () => [...(projectResourcesData?.items || []), ...(groupResourcesData?.items || [])],
    [projectResourcesData, groupResourcesData],
  );

  // ── Local state ──
  const [inputText, setInputText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [rightTab, setRightTab] = useState<RightTab>('tasks');
  const [leftTab, setLeftTab] = useState<'groups' | 'resources'>('groups');
  const [mainMode, setMainMode] = useState<MainMode>('chat');
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [resourceQuery, setResourceQuery] = useState('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState<ResourceType | 'all'>('all');
  const [resourceForm, setResourceForm] = useState<ResourceFormState>(emptyResourceForm);
  const [deletingResource, setDeletingResource] = useState<Resource | null>(null);
  const [showScrollBtns, setShowScrollBtns] = useState(false);
  const [chatSelectedAgent, setChatSelectedAgent] = useState<any>(null);
  const [editingGroup, setEditingGroup] = useState(false);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [projectTreeExpanded, setProjectTreeExpanded] = useState<Record<string, boolean>>({});
  const [projectTreeSelection, setProjectTreeSelection] = useState<TreeSelection>({});
  const [exportMode, setExportMode] = useState<ProjectBundleMode>('share');

  // ── Refs ──
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Chain views ──
  const {
    taskChainViews,
    chainViewCache,
    chainsLoading,
    forceExpandedChainIds,
    loadGroupChains,
    refreshLatestTaskChain,
    handleLoadSubChain,
    handleTaskClick,
  } = useChainViews({ groupId });

  // 任务变更后刷新群链视图 (创建/更新/状态变更/删除任务都会触发, 让内联 task chain 块即时更新)
  const refreshChains = useCallback(() => {
    void refreshLatestTaskChain();
  }, [refreshLatestTaskChain]);

  // ── Agent list ──
  const members = group?.members || [];
  const agentList = useMemo(() =>
    members
      .filter((m: any) => m.agent)
      .map((m: any) => ({ id: m.agent!.id, name: m.agent!.name, avatar: m.agent!.avatar })),
    [members]
  );

  // ── Chat stream (v2: POST + WebSocket) ──
  // 必须在 useWebSocket 之前调用, 这样 handleWsMessage 才能引用 handleStreamEvent
  const {
    activeReplyChain,
    isStreaming,
    streamingChainId,
    streamingPacketId,
    handleSend: chatStreamSend,
    handleStopStream,
    handleStreamEvent,
  } = useChatStream({
    groupId,
    group,
    members,
    agentList,
    taskChainViews,
    chainViewCache,
    refreshLatestTaskChain,
  });

  // ── WebSocket: 接收流式事件 + EventDispatcher 广播 ──
  // v2: chat stream 事件 (token/tool_call/tool_result/chain_end/done 等) 通过 WebSocket 推送,
  //     分发到 useChatStream.handleStreamEvent 处理。
  // 非 stream 事件 (agent_message/task_update) 由本回调直接处理。
  const handleWsMessage = useCallback((message: WsServerMessage) => {
    // Chat stream 事件 → 交给 useChatStream 处理
    if (STREAM_WS_TYPES.has(message.type)) {
      handleStreamEvent(message);
      return;
    }
    // 非流式事件
    if (message.type === 'agent_message') {
      // EventDispatcher 唤醒 assignee/lead 后, agent 回复完成广播
      const payload = message.payload as { chain_id?: string };
      if (payload?.chain_id) {
        void refreshLatestTaskChain(payload.chain_id);
      }
    } else if (message.type === 'task_update') {
      // 任务创建/状态变更 → 刷新 chain 视图 + group detail (任务列表嵌入在 group detail 中)
      void refreshLatestTaskChain();
      if (groupId) {
        void queryClient.invalidateQueries({ queryKey: groupKeys.detail(groupId) });
      }
    }
  }, [handleStreamEvent, refreshLatestTaskChain, queryClient, groupId]);

  useWebSocket(groupId ? `/groups/${groupId}` : '', {
    autoConnect: !!groupId,
    onMessage: handleWsMessage,
  });

  const hasMessages = taskChainViews.length > 0 || !!activeReplyChain;

  // ── Effects ──
  // 同步 URL groupId 到 store，让 PacketRenderer 能读取群级可见性覆盖。
  // activeGroupId 不持久化，刷新后必须从 URL 重新设置，否则群级设置失效。
  useEffect(() => {
    if (groupId && groupId !== activeGroupId) {
      setActiveGroupId(groupId);
    }
  }, [groupId, activeGroupId, setActiveGroupId]);

  useEffect(() => {
    if (groupLoading) return;
    loadGroupChains();
  }, [loadGroupChains, groupId, groupLoading]);

  const selectedResource = useMemo(
    () => allResources.find((resource: Resource) => resource.id === selectedResourceId) || allResources[0] || null,
    [allResources, selectedResourceId],
  );

  const filteredResources = useMemo(() => {
    const q = resourceQuery.trim().toLowerCase();
    return projectResources.filter((resource: Resource) => {
      const matchesType = resourceTypeFilter === 'all' || resource.type === resourceTypeFilter;
      const matchesQuery = !q
        || resource.title.toLowerCase().includes(q)
        || resource.content.toLowerCase().includes(q)
        || (resource.tags || []).some((tag: string) => tag.toLowerCase().includes(q));
      return matchesType && matchesQuery;
    });
  }, [projectResources, resourceQuery, resourceTypeFilter]);

  // ── Project tree ──
  const projectTreeNodes = useMemo(() => {
    if (!project) return [];
    return buildProjectContentTree({
      project,
      groups: sortedGroups,
      agents: projectAgentsData?.items || [],
      skills: skillsData?.items || [],
      resources: projectResources,
      tasks: [] as TaskListItem[],
      deliverables: deliverablesData?.items || [],
    });
  }, [project, sortedGroups, projectAgentsData?.items, skillsData?.items, projectResources, deliverablesData?.items]);

  const projectBundleSelection = useMemo(
    () => treeSelectionToBundleSelection(projectTreeNodes, projectTreeSelection, exportMode),
    [projectTreeNodes, projectTreeSelection, exportMode],
  );

  useEffect(() => {
    if (projectTreeNodes.length > 0) {
      setProjectTreeSelection(prev => {
        if (Object.keys(prev).length === 0) {
          return applyExportPreset(projectTreeNodes, exportMode);
        }
        return prev;
      });
    }
  }, [projectTreeNodes, exportMode]);

  const lastMutatedKeyRef = useRef('');
  useEffect(() => {
    if (mainMode === 'project-export' && projectId && !previewBundle.isPending) {
      const key = JSON.stringify(projectBundleSelection);
      if (key !== lastMutatedKeyRef.current) {
        lastMutatedKeyRef.current = key;
        previewBundle.mutate({ projectId, selection: projectBundleSelection });
      }
    }
  }, [mainMode, projectId, projectBundleSelection, previewBundle.isPending]);

  // ── Resource helpers ──
  const resourceHeadings = useMemo(() => extractMarkdownHeadings(selectedResource?.content || ''), [selectedResource?.content]);
  const resourceSaving = createResource.isPending || updateResource.isPending;

  useEffect(() => {
    if (!allResources.length) {
      setSelectedResourceId(null);
      return;
    }
    if (!selectedResourceId || !allResources.some((resource: Resource) => resource.id === selectedResourceId)) {
      setSelectedResourceId(allResources[0].id);
    }
  }, [allResources, selectedResourceId]);

  const openResource = (resource: Resource) => {
    setLeftTab('resources');
    setSelectedResourceId(resource.id);
    setMainMode('resource-view');
  };

  const startCreateResource = () => {
    navigate(`/workbench?projectId=${projectId}&mode=create`);
  };

  const startEditResource = () => {
    if (!selectedResource) return;
    navigate(`/workbench?projectId=${projectId}&resourceId=${selectedResource.id}&mode=edit`);
  };

  const cancelResourceForm = () => {
    setMainMode(selectedResource ? 'resource-view' : 'chat');
  };

  const handleSaveResource = async () => {
    const title = resourceForm.title.trim();
    const content = resourceForm.content.trim();
    if (!title || !content || !projectId) return;

    try {
      if (mainMode === 'resource-create') {
        const created = await createResource.mutateAsync({
          project_id: projectId,
          title,
          content,
          type: resourceForm.type,
          content_type: 'markdown',
          is_required: resourceForm.is_required,
          tags: parseResourceTags(resourceForm.tags),
        });
        setSelectedResourceId(created.id);
        toast.success('资料已创建');
      } else if (mainMode === 'resource-edit' && selectedResource) {
        await updateResource.mutateAsync({
          id: selectedResource.id,
          data: {
            title,
            content,
            type: resourceForm.type,
            is_required: resourceForm.is_required,
            tags: parseResourceTags(resourceForm.tags),
          },
        });
        toast.success('资料已更新');
      }
      setMainMode('resource-view');
    } catch (error) {
      console.error('[ChatPage] save resource failed:', error);
      toast.error(mainMode === 'resource-create' ? '创建资料失败' : '更新资料失败');
    }
  };

  const handleDeleteResource = async () => {
    if (!deletingResource) return;
    const deletingIndex = allResources.findIndex((resource: Resource) => resource.id === deletingResource.id);
    try {
      await deleteResource.mutateAsync(deletingResource.id);
      const next = allResources[deletingIndex + 1] || allResources[deletingIndex - 1] || null;
      setSelectedResourceId(next?.id || null);
      setDeletingResource(null);
      setMainMode(next ? 'resource-view' : 'chat');
      toast.success('资料已删除');
    } catch (error) {
      console.error('[ChatPage] delete resource failed:', error);
      toast.error('删除资料失败');
      throw error;
    }
  };

  // ── Auto-scroll ──
  useEffect(() => {
    if (taskChainViews.length === 0) return;
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    });
  }, [taskChainViews.length]);

  useEffect(() => {
    if (!activeReplyChain || activeReplyChain.chain.status !== 'active') return;
    if (!isNearBottomRef.current) return;
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'instant' });
    });
  }, [activeReplyChain?.packets]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setShowScrollBtns(distFromBottom > 200);
    isNearBottomRef.current = distFromBottom < 150;
  }, []);

  const scrollToTop = useCallback(() => {
    scrollContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const scrollToPrevMsg = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const chainEls = container.querySelectorAll('[data-chain]');
    const scrollTop = container.scrollTop;
    for (let i = chainEls.length - 1; i >= 0; i--) {
      const el = chainEls[i] as HTMLElement;
      if (el.offsetTop < scrollTop - 10) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
    }
    scrollToTop();
  }, [scrollToTop]);

  const scrollToNextMsg = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const chainEls = container.querySelectorAll('[data-chain]');
    const scrollTop = container.scrollTop;
    const clientHeight = container.clientHeight;
    for (let i = 0; i < chainEls.length; i++) {
      const el = chainEls[i] as HTMLElement;
      if (el.offsetTop > scrollTop + clientHeight + 10) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
    }
    scrollToBottom();
  }, [scrollToBottom]);

  // ── Project export ──
  const handleViewDeliverable = (delivId: string) => {
    navigate(`/workbench?projectId=${projectId}&resourceId=${delivId}&mode=view`);
  };

  const handleProjectExportMode = (mode: ProjectBundleMode) => {
    setExportMode(mode);
    setProjectTreeSelection(applyExportPreset(projectTreeNodes, mode));
  };

  const handleProjectExport = () => {
    if (!projectId || !project) return;
    const safeName = project.name.replace(/[\\/:*?"<>|\s]+/g, '_').replace(/^_+|_+$/g, '') || 'project';
    exportBundle.mutate({
      projectId,
      selection: projectBundleSelection,
      filename: `${safeName}_${exportMode}_bundle.zip`,
    });
  };

  // ── Loading / error guards ──
  if (projectLoading || groupLoading) {
    return (
      <div className="newspaper-bg min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground">加载中...</p>
        </div>
      </div>
    );
  }

  if (!project || !group) {
    return (
      <div className="newspaper-bg min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground mb-3">未选中群聊，请先进入项目并选择一个群组</p>
          <button onClick={() => navigate('/')} className="text-primary text-sm hover:underline">返回首页</button>
        </div>
      </div>
    );
  }

  // ── Context value ──
  const contextValue: ChatPageContextValue = {
    projectId: projectId || '',
    groupId: groupId || '',
    navigate,
    project,
    group,
    groupsData,
    projectAgentsData,
    projectResourcesData,
    skillsData,
    deliverablesData,
    mainMode,
    setMainMode,
    leftTab,
    setLeftTab,
    sortedGroups,
    activeGroupId,
    setActiveGroupId,
    creatingGroup,
    setCreatingGroup,
    rightTab,
    setRightTab,
    inputText,
    setInputText,
    isSending,
    setIsSending,
    isStreaming,
    streamingChainId,
    streamingPacketId,
    handleStopStream,
    activeReplyChain,
    taskChainViews,
    chainViewCache,
    chainsLoading,
    handleTaskClick,
    handleLoadSubChain,
    refreshChains,
    forceExpandedChainIds,
    members,
    agentList,
    hasMessages,
    chatStreamSend,
    scrollContainerRef,
    messagesEndRef,
    showScrollBtns,
    scrollToTop,
    scrollToBottom,
    scrollToPrevMsg,
    scrollToNextMsg,
    handleScroll,
    selectedResourceId,
    setSelectedResourceId,
    selectedResource,
    resourceQuery,
    setResourceQuery,
    resourceTypeFilter,
    setResourceTypeFilter,
    filteredResources,
    projectResources,
    groupResources,
    activeGroupName,
    openResource,
    startCreateResource,
    startEditResource,
    resourceForm,
    setResourceForm,
    resourceSaving,
    cancelResourceForm,
    handleSaveResource,
    resourceHeadings,
    deletingResource,
    setDeletingResource,
    chatSelectedAgent,
    setChatSelectedAgent,
    editingGroup,
    setEditingGroup,
    textareaRef,
    previewBundle,
    exportBundle,
    projectBundleSelection,
    projectTreeNodes,
    projectTreeExpanded,
    setProjectTreeExpanded,
    projectTreeSelection,
    setProjectTreeSelection,
    exportMode,
    setExportMode,
    handleProjectExport,
    handleProjectExportMode,
    handleViewDeliverable,
  };

  // ── Render ──
  return (
    <ChatPageContext.Provider value={contextValue}>
      <div data-cmp="ChatPage" className="h-screen newspaper-bg flex flex-col overflow-hidden">
        {mainMode === 'project-details' || mainMode === 'project-export' ? (
          <ProjectDetailsPanel />
        ) : (
          <>
            <ChatTopBar />
            <div className="flex flex-1 overflow-hidden">
              <LeftSidebar />
              <ChatPanel />
              <RightSidebar />
            </div>
          </>
        )}

        <ConfirmDialog
          open={!!deletingResource}
          onClose={() => setDeletingResource(null)}
          onConfirm={handleDeleteResource}
          title="删除资料"
          description={`确定要删除资料「${deletingResource?.title || ''}」吗？此操作不可撤销。`}
          confirmText="删除"
          destructive
        />

        {chatSelectedAgent && (
          <AgentCard
            agent={chatSelectedAgent.agent}
            groupRole={chatSelectedAgent.groupRole}
            joinedAt={chatSelectedAgent.joinedAt}
            memories={chatSelectedAgent.memories}
            onClose={() => setChatSelectedAgent(null)}
          />
        )}

        <EditGroupModal
          open={editingGroup}
          onClose={() => setEditingGroup(false)}
          onUpdated={() => setEditingGroup(false)}
          onDeleted={() => {
            setEditingGroup(false);
            navigate(`/project/${projectId}`);
          }}
          group={group}
          projectId={projectId || ''}
        />

        <CreateGroupModal
          open={creatingGroup}
          projectId={projectId || ''}
          onClose={() => setCreatingGroup(false)}
          onCreated={(id: string) => {
            setCreatingGroup(false);
            setActiveGroupId(id);
            navigate(`/project/${projectId}/chat/${id}`);
          }}
        />
      </div>
    </ChatPageContext.Provider>
  );
}
