import {
  MessageSquareIcon, ChevronRightIcon, SearchIcon, PlusIcon, FileTextIcon,
} from 'lucide-react';
import { useChatPage, groupStatusConfig, resourceTypeConfig, formatResourceDate } from './context';
import type { ResourceType, Resource } from '../../types';

export default function LeftSidebar() {
  const {
    leftTab, setLeftTab, mainMode, setMainMode,
    sortedGroups, activeGroupId, setActiveGroupId,
    navigate, projectId, creatingGroup, setCreatingGroup,
    projectResources, groupResources, activeGroupName,
    selectedResource, openResource, startCreateResource,
    resourceQuery, setResourceQuery, resourceTypeFilter, setResourceTypeFilter,
    filteredResources,
  } = useChatPage();

  return (
    <aside className="w-64 flex-shrink-0 border-r border-foreground/15 flex flex-col overflow-hidden">
      <div className="flex gap-1 p-2 border-b border-foreground/15 flex-shrink-0">
        <button
          onClick={() => { setLeftTab('groups'); setMainMode('chat'); }}
          className={`flex-1 text-xs py-1.5 font-newspaper transition-all duration-200 border-b-2 ${
            leftTab === 'groups' ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/40 hover:text-foreground/60'
          }`}
        >
          群聊列表
        </button>
        <button
          onClick={() => setLeftTab('resources')}
          className={`flex-1 text-xs py-1.5 font-newspaper transition-all duration-200 border-b-2 ${
            leftTab === 'resources' ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/40 hover:text-foreground/60'
          }`}
        >
          项目资料
        </button>
      </div>

      {/* Groups list */}
      <div className={`flex-1 overflow-y-auto p-1.5 flex flex-col gap-0.5 ${leftTab === 'groups' ? '' : 'hidden'}`}>
        <div className="flex items-center justify-between px-1 py-1">
          <span className="text-[10px] font-newspaper-bold text-foreground/40 uppercase tracking-wide">群聊</span>
          <button
            onClick={() => setCreatingGroup(true)}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-newspaper-bold text-foreground/60 hover:bg-foreground/5 transition-colors"
            title="创建群聊"
          >
            <PlusIcon className="h-3 w-3" />
            新建
          </button>
        </div>
        {sortedGroups.map(group => {
          const cfg = groupStatusConfig[group.status];
          const isActive = group.id === activeGroupId;
          return (
            <button
              key={group.id}
              onClick={() => {
                setActiveGroupId(group.id);
                navigate(`/project/${projectId}/chat/${group.id}`);
              }}
              className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-left transition-all duration-200 ${
                isActive ? 'border-l-2 border-foreground/60 bg-foreground/5' : 'hover:bg-foreground/5 border-l-2 border-transparent hover:border-foreground/20'
              }`}
            >
              <div className="w-1.5 h-1.5 flex-shrink-0 bg-foreground/60" />
              <div className="flex-1 min-w-0">
                <div className={`text-xs font-newspaper truncate ${isActive ? 'text-foreground/80' : 'text-foreground/60'}`}>
                  {group.name}
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <MessageSquareIcon className="w-2.5 h-2.5 text-foreground/30" />
                  <span className="text-[10px] text-foreground/30 font-newspaper">{group.message_count || 0} 条消息</span>
                </div>
              </div>
              <ChevronRightIcon className={`w-3 h-3 flex-shrink-0 ${isActive ? 'text-foreground/60' : 'text-foreground/30'}`} />
            </button>
          );
        })}
      </div>

      {/* Resources */}
      <div className={`flex-1 overflow-y-auto p-2 ${leftTab === 'resources' ? '' : 'hidden'}`}>
        <div className="flex h-full flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-newspaper-bold text-foreground/80">项目资料</div>
              <div className="text-[10px] text-foreground/30 font-newspaper">{projectResources.length + groupResources.length} 条资料</div>
            </div>
            <button
              onClick={startCreateResource}
              className="flex items-center gap-1 border border-foreground/30 px-2 py-1 text-[10px] font-newspaper-bold text-foreground/60 hover:bg-foreground/5 transition-colors"
            >
              <PlusIcon className="h-3 w-3" />
              新建
            </button>
          </div>

          <div className="relative">
            <SearchIcon className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-foreground/30" />
            <input
              value={resourceQuery}
              onChange={event => setResourceQuery(event.target.value)}
              placeholder="搜索资料"
              className="w-full border-b border-foreground/20 bg-transparent py-1.5 pl-7 pr-3 text-xs text-foreground/80 outline-none focus:border-foreground/40 font-newspaper placeholder:text-foreground/20"
            />
          </div>

          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setResourceTypeFilter('all')}
              className={`px-1.5 py-0.5 text-[10px] font-newspaper border-b ${resourceTypeFilter === 'all' ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/30'}`}
            >
              全部
            </button>
            {(Object.entries(resourceTypeConfig) as Array<[ResourceType, typeof resourceTypeConfig[ResourceType]]>).map(([type, cfg]) => (
              <button
                key={type}
                onClick={() => setResourceTypeFilter(type)}
                className={`px-1.5 py-0.5 text-[10px] font-newspaper border-b ${resourceTypeFilter === type ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/30'}`}
              >
                {cfg.label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto flex flex-col gap-3">
            {/* 群内资料 (当前激活群写出的资料, group_id 非空) */}
            {groupResources.length > 0 && (
              <ResourceSection
                title={activeGroupName ? `${activeGroupName} · 群内资料` : '群内资料'}
                resources={groupResources}
                resourceQuery={resourceQuery}
                resourceTypeFilter={resourceTypeFilter}
                selectedResource={selectedResource}
                mainMode={mainMode}
                openResource={openResource}
              />
            )}

            {/* 全局资料 (项目级, group_id IS NULL) */}
            <ResourceSection
              title="全局资料"
              resources={projectResources}
              resourceQuery={resourceQuery}
              resourceTypeFilter={resourceTypeFilter}
              selectedResource={selectedResource}
              mainMode={mainMode}
              openResource={openResource}
            />

            {projectResources.length === 0 && groupResources.length === 0 && (
              <div className="flex h-full min-h-32 flex-col items-center justify-center border border-dashed border-foreground/15 px-3 text-center">
                <FileTextIcon className="mb-1.5 h-5 w-5 text-foreground/20" />
                <div className="text-[10px] font-newspaper-bold text-foreground/60">暂无资料</div>
                <div className="mt-0.5 text-[10px] text-foreground/30 font-newspaper">新建后会在对话区展示</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

/** 资源子分区：复用搜索/类型过滤逻辑，渲染一个分组标题 + 资源卡片列表 */
function ResourceSection({
  title, resources, resourceQuery, resourceTypeFilter,
  selectedResource, mainMode, openResource,
}: {
  title: string;
  resources: Resource[];
  resourceQuery: string;
  resourceTypeFilter: ResourceType | 'all';
  selectedResource: Resource | null;
  mainMode: string;
  openResource: (resource: Resource) => void;
}) {
  const q = resourceQuery.trim().toLowerCase();
  const list = resources.filter(resource => {
    const matchesType = resourceTypeFilter === 'all' || resource.type === resourceTypeFilter;
    const matchesQuery = !q
      || resource.title.toLowerCase().includes(q)
      || resource.content.toLowerCase().includes(q)
      || (resource.tags || []).some((tag: string) => tag.toLowerCase().includes(q));
    return matchesType && matchesQuery;
  });

  if (list.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="text-[10px] font-newspaper-bold text-foreground/40 uppercase tracking-wide px-0.5">
        {title} · {list.length}
      </div>
      <div className="flex flex-col gap-1.5">
        {list.map(resource => {
          const cfg = resourceTypeConfig[resource.type] || resourceTypeConfig.custom;
          const Icon = cfg.icon;
          const active = resource.id === selectedResource?.id && mainMode.startsWith('resource');
          return (
            <button
              key={resource.id}
              onClick={() => openResource(resource)}
              className={`w-full border p-2 text-left transition-all ${active ? 'border-foreground/30 bg-foreground/5' : 'border-foreground/15 bg-transparent hover:border-foreground/30'}`}
            >
              <div className="flex items-start gap-2">
                <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center text-foreground/60">
                  <Icon className="h-3 w-3" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] font-newspaper-bold text-foreground/80">{resource.title}</div>
                  <div className="mt-0.5 line-clamp-1 text-[10px] leading-relaxed text-foreground/30 font-newspaper">{resource.content_type === 'markdown' ? resource.content : `[${resource.content_type}] ${resource.content.slice(0, 50)}`}</div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-foreground/30 font-newspaper">
                    <span className="border border-foreground/15 px-1.5 py-px">{cfg.label}</span>
                    <span>{formatResourceDate(resource.updated_at || resource.created_at)}</span>
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
