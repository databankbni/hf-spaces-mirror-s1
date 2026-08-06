import { useState, useEffect, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  ArrowLeftIcon,
  PlusIcon,
  EditIcon,
  TrashIcon,
  SaveIcon,
  EyeIcon,
  FileTextIcon,
  BookOpenIcon,
  LightbulbIcon,
  MapIcon,
  XIcon,
  BracesIcon,
  TableIcon,
  ListIcon,
  GitBranchIcon,
  LayoutGridIcon,
  BarChart3Icon,
  ClockIcon,
} from 'lucide-react';
import { Resource, ResourceType, ContentType, CreateResourceRequest, UpdateResourceRequest } from '../types';
import { useProjectResources, useCreateResource, useUpdateResource, useDeleteResource } from '../hooks/useResources';
import { useDeliverablesByProject } from '../hooks/useDeliverables';
import MarkdownRenderer from '../components/markdown/MarkdownRenderer';
import RenderEngine from '../render-engine/RenderEngine';
import ConfirmDialog from '../components/ConfirmDialog';
import { cn } from '@/lib/utils';

// ── 类型配置 ──

const typeConfig: Record<ResourceType, { icon: typeof FileTextIcon; label: string; color: string; chip: string }> = {
  note: { icon: FileTextIcon, label: '笔记', color: 'opacity-60', chip: 'opacity-60' },
  reference: { icon: BookOpenIcon, label: '参考资料', color: 'opacity-60', chip: 'opacity-60' },
  guideline: { icon: LightbulbIcon, label: '指南', color: 'opacity-60', chip: 'opacity-60' },
  rule: { icon: FileTextIcon, label: '规则', color: 'opacity-60', chip: 'opacity-60' },
  custom: { icon: FileTextIcon, label: '自定义', color: 'opacity-60', chip: 'opacity-60' },
  map: { icon: MapIcon, label: '地图', color: 'opacity-60', chip: 'opacity-60' },
};

// ── 内容类型配置 ──

const contentTypeConfig: Record<ContentType, { label: string; icon: typeof FileTextIcon; description: string }> = {
  text: { label: '纯文本', icon: FileTextIcon, description: '纯文本内容' },
  markdown: { label: 'Markdown', icon: FileTextIcon, description: '富文本文档，支持标题、列表、代码块等' },
  json: { label: 'JSON', icon: BracesIcon, description: '原始 JSON 数据' },
  table: { label: '表格', icon: TableIcon, description: '结构化表格数据' },
  list: { label: '列表', icon: ListIcon, description: '列表展示' },
  tree: { label: '树形', icon: GitBranchIcon, description: '层级树形结构' },
  document: { label: '文档', icon: FileTextIcon, description: '文档渲染视图' },
  card: { label: '卡片', icon: LayoutGridIcon, description: '卡片网格布局' },
  stat: { label: '统计', icon: BarChart3Icon, description: '统计指标面板' },
  timeline: { label: '时间线', icon: ClockIcon, description: '时间线展示' },
  map: { label: '地图', icon: MapIcon, description: '网格地图编辑器' },
};

// ── 判断 content_type 的编辑/预览模式 ──

function getEditorMode(contentType: ContentType): 'markdown' | 'map' | 'json' {
  if (contentType === 'markdown') return 'markdown';
  if (contentType === 'map') return 'map';
  return 'json';
}

// ── 各 content_type 的默认 JSON 模板 ──

const contentTypeTemplates: Partial<Record<ContentType, string>> = {
  table: JSON.stringify([
    { id: 1, name: '示例项目A', status: '进行中', priority: '高' },
    { id: 2, name: '示例项目B', status: '已完成', priority: '中' },
    { id: 3, name: '示例项目C', status: '待开始', priority: '低' },
  ], null, 2),

  list: JSON.stringify([
    { title: '需求分析', author: 'Alice', date: '2026-05-28' },
    { title: '原型设计', author: 'Bob', date: '2026-05-29' },
    { title: '开发实现', author: 'Charlie', date: '2026-05-30' },
  ], null, 2),

  tree: JSON.stringify([
    {
      id: 'root',
      kind: 'project',
      label: '项目根节点',
      children: [
        {
          id: 'branch-1',
          kind: 'folder',
          label: '前端模块',
          children: [
            { id: 'leaf-1', kind: 'task', label: '页面设计', badge: 'done' },
            { id: 'leaf-2', kind: 'task', label: '组件开发', badge: 'in progress' },
          ],
        },
        {
          id: 'branch-2',
          kind: 'folder',
          label: '后端模块',
          children: [
            { id: 'leaf-3', kind: 'task', label: 'API 设计' },
            { id: 'leaf-4', kind: 'task', label: '数据库建模' },
          ],
        },
      ],
    },
  ], null, 2),

  document: JSON.stringify({
    content: '# 文档标题\n\n这是一个文档示例。\n\n## 第一章\n\n正文内容，支持 **Markdown** 格式。\n\n## 第二章\n\n- 列表项 1\n- 列表项 2\n- 列表项 3',
  }, null, 2),

  card: JSON.stringify([
    { name: '用户服务', status: '运行中', uptime: '99.9%', region: '华东' },
    { name: '订单服务', status: '运行中', uptime: '99.5%', region: '华北' },
    { name: '支付服务', status: '维护中', uptime: '98.0%', region: '华南' },
  ], null, 2),

  stat: JSON.stringify({
    metrics: [
      { label: '总任务数', value: 142, icon: 'bar-chart', color: 'blue' },
      { label: '已完成', value: 98, icon: 'trending-up', color: 'green' },
      { label: '进行中', value: 32, icon: 'list-checks', color: 'amber' },
      { label: '活跃 Agent', value: 5, icon: 'users', color: 'violet' },
    ],
  }, null, 2),

  timeline: JSON.stringify([
    { created_at: '2026-05-30T10:00:00Z', title: '项目启动', description: '完成项目立项和团队组建' },
    { created_at: '2026-05-28T14:00:00Z', title: '需求评审', description: '通过产品需求文档评审' },
    { created_at: '2026-05-25T09:00:00Z', title: '技术选型', description: '确定技术栈和架构方案' },
  ], null, 2),

  json: JSON.stringify({ key: 'value', nested: { a: 1, b: 2 } }, null, 2),
};

// ── 辅助函数 ──

function formatDate(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function parseTags(raw: string) {
  return raw
    .split(/[,，\n]/)
    .map(tag => tag.trim())
    .filter(Boolean);
}

// ── 表单状态 ──

type Mode = 'view' | 'edit' | 'create';

interface ResourceFormState {
  title: string;
  content: string;
  type: ResourceType;
  content_type: ContentType;
}

const emptyForm: ResourceFormState = {
  title: '',
  content: '',
  type: 'note',
  content_type: 'markdown',
};

function toForm(resource: Resource): ResourceFormState {
  return {
    title: resource.title,
    content: resource.content,
    type: resource.type,
    content_type: resource.content_type || 'markdown',
  };
}

// ── 主组件 ──

export default function WorkbenchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const projectId = searchParams.get('projectId') || '';
  const resourceId = searchParams.get('resourceId') || '';
  const modeParam = searchParams.get('mode') as Mode | null;
  const mode: Mode = modeParam === 'edit' || modeParam === 'create' ? modeParam : 'view';

  // 数据
  const { data: resourcesData, isLoading: resourcesLoading } = useProjectResources(projectId);
  const resources: Resource[] = (resourcesData as any)?.items ?? (Array.isArray(resourcesData) ? resourcesData : []);
  const { data: deliverablesData } = useDeliverablesByProject(projectId);
  const deliverables: any[] = (deliverablesData as any)?.items ?? [];
  const createResource = useCreateResource();
  const updateResource = useUpdateResource();
  const deleteResource = useDeleteResource();

  // 本地状态
  const [typeFilter, setTypeFilter] = useState<ResourceType | 'all'>('all');
  const [form, setForm] = useState<ResourceFormState>(emptyForm);
  const [deleting, setDeleting] = useState<Resource | null>(null);
  const [createType, setCreateType] = useState<ResourceType | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  // 当前选中的资源（含交付物转为 Resource 格式）
  const selectedResource = useMemo(() => {
    const found = resources.find((r: Resource) => r.id === resourceId);
    if (found) return found;
    // 检查是否选中了交付物
    const deliv = deliverables.find((d: any) => d.id === resourceId);
    if (deliv) {
      return {
        id: deliv.id,
        project_id: projectId,
        group_id: null,
        title: deliv.title,
        content: deliv.content || '',
        content_type: 'markdown' as const,
        type: 'custom' as ResourceType,
        tags: [],
        is_required: false,
        created_by: deliv.author_id || 'agent',
        created_at: deliv.created_at,
        updated_at: deliv.updated_at,
      } as Resource;
    }
    return null;
  }, [resources, deliverables, resourceId, projectId]);

  // 同步 form 状态
  useEffect(() => {
    if (mode === 'edit' && selectedResource) {
      setForm(toForm(selectedResource));
    } else if (mode === 'create') {
      if (createType) {
        setForm({ ...emptyForm, type: createType });
      } else {
        setForm(emptyForm);
      }
    }
  }, [mode, selectedResource, createType]);

  // 过滤资源
  const filteredResources = useMemo(() => {
    return resources.filter((r: Resource) => typeFilter === 'all' || r.type === typeFilter);
  }, [resources, typeFilter]);

  // URL 状态更新
  const updateUrl = (params: { resourceId?: string; mode?: Mode }) => {
    const next = new URLSearchParams(searchParams);
    if (params.resourceId !== undefined) next.set('resourceId', params.resourceId);
    if (params.mode !== undefined) next.set('mode', params.mode);
    setSearchParams(next, { replace: true });
  };

  // ── 操作 ──

  const handleSelect = (resource: Resource) => {
    updateUrl({ resourceId: resource.id, mode: 'view' });
  };

  const handleNew = () => {
    setCreateType(null);
    updateUrl({ mode: 'create', resourceId: '' });
  };

  const handleSelectCreateType = (type: ResourceType) => {
    if (type === 'map') {
      navigate(`/map-editor?projectId=${projectId}`);
      return;
    }
    setCreateType(type);
    setForm({ ...emptyForm, type, content_type: 'markdown' });
    updateUrl({ mode: 'create' });
  };

  const handleEdit = () => {
    if (!selectedResource) return;
    setForm(toForm(selectedResource));
    updateUrl({ mode: 'edit' });
  };

  const handleCancel = () => {
    if (selectedResource) {
      updateUrl({ mode: 'view' });
    } else {
      updateUrl({ mode: 'view', resourceId: '' });
    }
  };

  const handleSave = async () => {
    const title = form.title.trim();
    const content = form.content.trim();
    if (!title || !projectId) return;

    try {
      if (mode === 'create') {
        const created = await createResource.mutateAsync({
          project_id: projectId,
          title,
          content,
          type: form.type,
          content_type: form.content_type,
        });
        updateUrl({ resourceId: created.id, mode: 'view' });
        toast.success('资料已创建');
      } else if (mode === 'edit' && selectedResource) {
        await updateResource.mutateAsync({
          id: selectedResource.id,
          data: { title, content, type: form.type },
        });
        updateUrl({ mode: 'view' });
        toast.success('资料已更新');
      }
    } catch (error) {
      console.error('[WorkbenchPage] save failed:', error);
      toast.error(mode === 'create' ? '创建资料失败' : '更新资料失败');
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    const deletingIndex = resources.findIndex((r: Resource) => r.id === deleting.id);
    try {
      await deleteResource.mutateAsync(deleting.id);
      const next = resources[deletingIndex + 1] || resources[deletingIndex - 1] || null;
      updateUrl({ resourceId: next?.id || '', mode: 'view' });
      setDeleting(null);
      toast.success('资料已删除');
    } catch (error) {
      console.error('[WorkbenchPage] delete failed:', error);
      toast.error('删除资料失败');
      throw error;
    }
  };

  const saving = createResource.isPending || updateResource.isPending;

  // ── 渲染：顶部工具栏 ──

  const renderToolbar = () => (
    <div className="flex items-center justify-between border-b-2 border-double border-current px-5 py-3">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(`/project/${projectId}`)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm transition-opacity hover:opacity-80"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          返回
        </button>
        <div className="h-5 w-px bg-border" />
        <h1 className="text-base font-bold font-newspaper text-foreground">数据工作台</h1>
      </div>
      {projectId && (
        <span className="border border-current px-3 py-1 text-xs opacity-60">
          项目 {projectId.slice(0, 8)}
        </span>
      )}
    </div>
  );

  // ── 渲染：左侧资源列表 ──

  const renderLeftPanel = () => (
    <div className="flex w-64 flex-shrink-0 flex-col border-r-2 border-double border-current">
      {/* 新建按钮 */}
      <div className="border-b border-border p-4">
        <button
          onClick={handleNew}
          className="flex w-full items-center justify-center gap-1.5 border border-current py-2 text-sm font-medium transition-opacity hover:opacity-80"
        >
          <PlusIcon className="h-4 w-4" />
          新建资料
        </button>
      </div>

      {/* 类型筛选 */}
      <div className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setTypeFilter('all')}
            className={cn(
              'border border-current px-2.5 py-1 text-xs transition-all',
              typeFilter === 'all' ? 'opacity-100' : 'opacity-50 hover:opacity-80',
            )}
          >
            全部
          </button>
          {(Object.entries(typeConfig) as Array<[ResourceType, typeof typeConfig[ResourceType]]>).map(([type, cfg]) => (
            <button
              key={type}
              onClick={() => setTypeFilter(type)}
              className={cn(
                'border border-current px-2.5 py-1 text-xs transition-all',
                typeFilter === type ? 'opacity-100' : 'opacity-50 hover:opacity-80',
              )}
            >
              {cfg.label}
            </button>
          ))}
        </div>
      </div>

      {/* 资源列表 */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {resourcesLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <span className="text-sm">加载中...</span>
          </div>
        ) : filteredResources.length === 0 && deliverables.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <FileTextIcon className="mb-3 h-8 w-8 opacity-40" />
            <span className="text-sm">暂无资料</span>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {/* 资源 */}
            {filteredResources.map((resource: Resource) => {
              const cfg = typeConfig[resource.type] || typeConfig.custom;
              const Icon = cfg.icon;
              const active = resource.id === resourceId && mode === 'view';
              return (
                <button
                  key={resource.id}
                  onClick={() => handleSelect(resource)}
                  className={cn(
                    'flex items-center gap-2.5 border border-transparent px-3 py-2.5 text-left transition-all',
                    active ? 'border-current text-foreground' : 'text-foreground hover:opacity-80',
                  )}
                >
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center border border-current opacity-60">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{resource.title}</div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="border border-current px-1.5 py-0.5 opacity-60">{cfg.label}</span>
                      <span>{formatDate(resource.updated_at || resource.created_at)}</span>
                    </div>
                  </div>
                </button>
              );
            })}

            {/* 交付物（与资料混排，用不同标签区分） */}
            {deliverables.map((d: any) => {
              const active = d.id === resourceId;
              return (
                <button
                  key={d.id}
                  onClick={() => updateUrl({ resourceId: d.id, mode: 'view' })}
                  className={cn(
                    'flex items-center gap-2.5 border border-transparent px-3 py-2.5 text-left transition-all',
                    active ? 'border-current text-foreground' : 'text-foreground hover:opacity-80',
                  )}
                >
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center border border-current opacity-60">
                    <FileTextIcon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{d.title}</div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="border border-current px-1.5 py-0.5 opacity-60">交付物</span>
                      <span>{formatDate(d.updated_at || d.created_at)}</span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  // ── 渲染：创建模式 - 类型选择 ──

  const handleSelectContentType = (ct: ContentType) => {
    if (ct === 'map') {
      navigate(`/map-editor?projectId=${projectId}`);
      return;
    }
    const template = contentTypeTemplates[ct] || '';
    setCreateType('note');
    setForm({ ...emptyForm, type: 'note', content_type: ct, content: template });
    updateUrl({ mode: 'create' });
  };

  const renderCreateTypeSelector = () => (
    <div className="flex h-full flex-col items-center justify-center newspaper-bg p-8">
      <div className="mb-8 text-center">
        <h2 className="text-xl font-bold font-newspaper text-foreground">选择资料格式</h2>
        <p className="mt-2 text-sm text-muted-foreground">选择内容显示方式，创建后可随时切换</p>
      </div>
      <div className="grid max-w-3xl grid-cols-4 gap-4">
        {(Object.entries(contentTypeConfig) as Array<[ContentType, typeof contentTypeConfig[ContentType]]>).map(([ct, cfg]) => {
          const Icon = cfg.icon;
          return (
            <button
              key={ct}
              onClick={() => handleSelectContentType(ct)}
              className="group flex flex-col items-center gap-3 border border-current p-5 transition-all hover:opacity-80"
            >
              <div className="flex h-11 w-11 items-center justify-center border border-current text-muted-foreground transition-colors opacity-60 group-hover:opacity-100">
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-sm font-medium text-foreground">{cfg.label}</div>
              <div className="text-[11px] leading-tight text-muted-foreground">{cfg.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );

  // ── 渲染：查看模式 ──

  const renderViewMode = () => {
    if (!selectedResource) {
      return (
        <div className="flex h-full flex-col items-center justify-center newspaper-bg p-8">
          <FileTextIcon className="mb-4 h-12 w-12 text-muted-foreground/30" />
          <div className="text-base font-semibold text-foreground">选择或创建资料</div>
          <div className="mt-2 text-sm text-muted-foreground">从左侧列表选择资料，或点击「新建资料」开始创建</div>
        </div>
      );
    }

    const cfg = typeConfig[selectedResource.type] || typeConfig.custom;
    const Icon = cfg.icon;

    return (
      <div className="flex h-full flex-col newspaper-bg">
        {/* 顶部信息栏 */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex items-center gap-2">
              <span className={cn('inline-flex items-center gap-1.5 border border-current px-2.5 py-1 text-xs font-medium', cfg.chip)}>
                <Icon className="h-3.5 w-3.5" />
                {cfg.label}
              </span>
            </div>
            <h2 className="truncate text-lg font-bold font-newspaper text-foreground">{selectedResource.title}</h2>
          </div>
          <div className="flex items-center gap-2">
            {selectedResource.content_type === 'map' && (
              <button
                onClick={() => navigate(`/map-editor?projectId=${projectId}&resourceId=${selectedResource.id}`)}
                className="flex items-center gap-1.5 border border-current px-3 py-1.5 text-xs transition-opacity hover:opacity-80"
              >
                <MapIcon className="h-3.5 w-3.5" />
                编辑地图
              </button>
            )}
            <button
              onClick={handleEdit}
              className="flex items-center gap-1.5 border border-current px-3 py-1.5 text-xs transition-opacity hover:opacity-80"
            >
              <EditIcon className="h-3.5 w-3.5" />
              编辑
            </button>
            <button
              onClick={() => setDeleting(selectedResource)}
              className="flex items-center gap-1.5 border border-current px-3 py-1.5 text-xs transition-opacity hover:opacity-80"
            >
              <TrashIcon className="h-3.5 w-3.5" />
              删除
            </button>
          </div>
        </div>

        {/* 内容区域 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {selectedResource.content_type === 'markdown' ? (
            <MarkdownRenderer content={selectedResource.content} className="mx-auto max-w-3xl" />
          ) : selectedResource.content_type === 'map' ? (
            (() => {
              try {
                const mapConfig = JSON.parse(selectedResource.content);
                return (
                  <RenderEngine spec={{
                    version: 1,
                    view_type: 'map',
                    title: selectedResource.title,
                    data: {},
                    options: { map: mapConfig },
                    style: { bordered: true },
                  }} />
                );
              } catch {
                return <div className="text-sm text-destructive">地图数据解析失败</div>;
              }
            })()
          ) : (
            (() => {
              try {
                const parsed = JSON.parse(selectedResource.content);
                const viewType = selectedResource.content_type as import('../render-engine/types').ViewType;
                return (
                  <RenderEngine spec={{
                    version: 1,
                    view_type: viewType,
                    title: selectedResource.title,
                    data: parsed,
                    style: { bordered: true },
                  }} />
                );
              } catch {
                // JSON 解析失败，回退到 markdown 渲染
                return <MarkdownRenderer content={selectedResource.content} className="mx-auto max-w-3xl" />;
              }
            })()
          )}
        </div>
      </div>
    );
  };

  // ── 渲染：编辑模式 ──

  const renderEditMode = () => {
    const editorMode = getEditorMode(form.content_type);

    return (
      <div className="flex h-full flex-col newspaper-bg">
        {/* 顶部编辑栏 */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex items-center gap-3">
              <input
                value={form.title}
                onChange={e => setForm(prev => ({ ...prev, title: e.target.value }))}
                className="flex-1 border border-current px-3 py-1.5 text-sm font-medium outline-none focus:opacity-80"
                placeholder="资料标题"
              />
              <div className="flex flex-wrap gap-1.5">
                {(Object.entries(typeConfig) as Array<[ResourceType, typeof typeConfig[ResourceType]]>).map(([type, cfg]) => (
                  <button
                    key={type}
                    onClick={() => setForm(prev => ({ ...prev, type }))}
                    className={cn(
                      'border border-current px-2.5 py-1 text-xs transition-all',
                      form.type === type ? 'opacity-100' : 'opacity-50 hover:opacity-80',
                    )}
                  >
                    {cfg.label}
                  </button>
                ))}
              </div>
            </div>
            {/* 内容类型选择器 */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">显示方式:</span>
              <div className="flex flex-wrap gap-1">
                {(Object.entries(contentTypeConfig) as Array<[ContentType, typeof contentTypeConfig[ContentType]]>).map(([ct, cfg]) => {
                  const CtIcon = cfg.icon;
                  return (
                    <button
                      key={ct}
                      onClick={() => {
                        setForm(prev => {
                          // 切换类型时，如果内容为空或还是模板内容，自动填充新模板
                          const isContentEmpty = !prev.content.trim();
                          const isDefaultTitle = !prev.title.trim() || prev.title === '无标题';
                          const shouldFillTemplate = isContentEmpty || isDefaultTitle;
                          const newContent = shouldFillTemplate ? (contentTypeTemplates[ct] || '') : prev.content;
                          return { ...prev, content_type: ct, content: newContent };
                        });
                      }}
                      className={cn(
                        'flex items-center gap-1 border border-current px-2 py-1 text-xs transition-all',
                        form.content_type === ct ? 'opacity-100' : 'opacity-50 hover:opacity-80',
                      )}
                      title={cfg.description}
                    >
                      <CtIcon className="h-3 w-3" />
                      {cfg.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCancel}
              disabled={saving}
              className="border border-current px-3 py-1.5 text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={() => {
                if (!form.title.trim()) {
                  toast.error('请填写资料标题');
                  return;
                }
                handleSave();
              }}
              disabled={saving}
              className={cn(
                'flex items-center gap-1.5 border border-current px-3 py-1.5 text-xs font-medium transition-opacity',
                saving ? 'opacity-50 cursor-not-allowed' : 'opacity-80 hover:opacity-100',
              )}
            >
              <SaveIcon className="h-3.5 w-3.5" />
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>

        {/* 编辑区域 */}
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {editorMode === 'map' ? (
            <div className="flex flex-col gap-4">
              {/* 地图编辑器入口 */}
              <div className="border border-dashed border-current p-8 text-center opacity-60">
                <MapIcon className="mx-auto mb-3 h-10 w-10 opacity-60" />
                <div className="mb-1 text-sm font-medium text-foreground">地图类型资料</div>
                <div className="mb-4 text-xs text-muted-foreground">
                  {form.content
                    ? '当前已有地图数据，点击下方按钮在编辑器中修改'
                    : '点击下方按钮打开地图编辑器，绘制地图后保存'}
                </div>
                <button
                  onClick={() => {
                    if (mode === 'edit' && selectedResource) {
                      navigate(`/map-editor?projectId=${projectId}&resourceId=${selectedResource.id}`);
                    } else {
                      navigate(`/map-editor?projectId=${projectId}`);
                    }
                  }}
                  className="inline-flex items-center gap-2 border border-current px-4 py-2 text-sm font-medium transition-opacity hover:opacity-80"
                >
                  <MapIcon className="h-4 w-4" />
                  打开地图编辑器
                </button>
              </div>

              {/* JSON 高级编辑 */}
              <div>
                <div className="mb-2 text-xs font-medium text-muted-foreground">地图 JSON 数据（高级编辑）</div>
                <textarea
                  value={form.content}
                  onChange={e => setForm(prev => ({ ...prev, content: e.target.value }))}
                  rows={12}
                  className="w-full border border-current px-3 py-3 font-mono text-xs leading-relaxed text-foreground outline-none focus:opacity-80"
                  placeholder='{"grid":{"cols":10,"rows":10,"cell_shape":"square"},"territories":[]}'
                />
              </div>
            </div>
          ) : editorMode === 'markdown' ? (
            <div className="flex h-full gap-4">
              {/* 编辑区 */}
              <div className="flex flex-1 flex-col">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">Markdown 编辑</span>
                  <button
                    onClick={() => setShowPreview(!showPreview)}
                    className="flex items-center gap-1 border border-current px-2 py-1 text-xs transition-opacity hover:opacity-80"
                  >
                    <EyeIcon className="h-3.5 w-3.5" />
                    {showPreview ? '隐藏预览' : '显示预览'}
                  </button>
                </div>
                <textarea
                  value={form.content}
                  onChange={e => setForm(prev => ({ ...prev, content: e.target.value }))}
                  className="min-h-96 flex-1 border border-current px-4 py-3 font-mono text-sm leading-relaxed text-foreground outline-none focus:opacity-80"
                  placeholder="# 标题\n\n写下资料内容，支持列表、表格、代码块和链接。"
                />
              </div>

              {/* 实时预览 */}
              {showPreview && (
                <div className="flex-1 overflow-y-auto border border-current p-4">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">预览</div>
                  <MarkdownRenderer content={form.content} />
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full gap-4">
              {/* JSON 编辑区 */}
              <div className="flex flex-1 flex-col">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">JSON 数据编辑</span>
                  <button
                    onClick={() => setShowPreview(!showPreview)}
                    className="flex items-center gap-1 border border-current px-2 py-1 text-xs transition-opacity hover:opacity-80"
                  >
                    <EyeIcon className="h-3.5 w-3.5" />
                    {showPreview ? '隐藏预览' : '显示预览'}
                  </button>
                </div>
                <textarea
                  value={form.content}
                  onChange={e => setForm(prev => ({ ...prev, content: e.target.value }))}
                  className="min-h-96 flex-1 border border-current px-4 py-3 font-mono text-sm leading-relaxed text-foreground outline-none focus:opacity-80"
                  placeholder={`// 输入 ${contentTypeConfig[form.content_type]?.label || form.content_type} 类型的 JSON 数据\n{}`}
                />
              </div>

              {/* RenderEngine 实时预览 */}
              {showPreview && (
                <div className="flex-1 overflow-y-auto border border-current p-4">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">预览</div>
                  {(() => {
                    try {
                      const parsed = JSON.parse(form.content);
                      const viewType = form.content_type as import('../render-engine/types').ViewType;
                      return <RenderEngine spec={{ version: 1, view_type: viewType, data: parsed, style: { bordered: true } }} />;
                    } catch {
                      return <div className="text-xs text-muted-foreground">输入有效的 JSON 数据后预览</div>;
                    }
                  })()}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── 渲染：右侧内容区 ──

  const renderRightPanel = () => {
    if (mode === 'create' && !createType) {
      return renderCreateTypeSelector();
    }
    if (mode === 'create' || mode === 'edit') {
      return renderEditMode();
    }
    return renderViewMode();
  };

  // ── 主渲染 ──

  return (
    <div className="flex h-screen flex-col newspaper-bg font-newspaper">
      {renderToolbar()}
      <div className="flex min-h-0 flex-1">
        {renderLeftPanel()}
        <div className="min-w-0 flex-1">{renderRightPanel()}</div>
      </div>

      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={handleDelete}
        title="删除资料"
        description={`确定要删除资料「${deleting?.title || ''}」吗？此操作不可撤销。`}
        confirmText="删除"
        destructive
      />
    </div>
  );
}
