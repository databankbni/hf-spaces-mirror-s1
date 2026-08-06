import {
  FileTextIcon, SaveIcon, PlusIcon, EditIcon, TrashIcon, GitBranchIcon,
} from 'lucide-react';
import { useChatPage, resourceTypeConfig, formatResourceDate } from './context';
import { Switch } from '../../components/ui/switch';
import MarkdownRenderer from '../../components/markdown/MarkdownRenderer';
import RenderEngine from '../../render-engine/RenderEngine';

export default function ResourcePanel() {
  const {
    mainMode, setMainMode,
    selectedResource,
    resourceForm, setResourceForm,
    resourceSaving,
    cancelResourceForm, handleSaveResource,
    resourceHeadings,
    startCreateResource, startEditResource,
    setDeletingResource,
  } = useChatPage();

  if (mainMode === 'resource-create' || mainMode === 'resource-edit') {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-foreground/15 px-4 py-3">
          <div>
            <div className="text-sm font-newspaper-bold text-foreground/80">{mainMode === 'resource-create' ? '新建项目资料' : '修改项目资料'}</div>
            <div className="text-[10px] text-foreground/30 font-newspaper">在对话主区域编辑，保存后切回资料渲染展示区</div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={cancelResourceForm} disabled={resourceSaving} className="px-3 py-1.5 text-sm text-foreground/40 hover:bg-foreground/5 hover:text-foreground/80 disabled:opacity-50 font-newspaper">取消</button>
            <button
              onClick={handleSaveResource}
              disabled={resourceSaving || !resourceForm.title.trim() || !resourceForm.content.trim()}
              className="flex items-center gap-1.5 border border-foreground/30 px-4 py-2 text-sm font-newspaper-bold text-foreground/80 hover:bg-foreground/5 disabled:opacity-50"
            >
              <SaveIcon className="h-4 w-4" />
              {resourceSaving ? '保存中...' : '保存资料'}
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mx-auto grid max-w-5xl gap-4">
            <label className="grid gap-1.5">
              <span className="text-xs font-newspaper text-foreground/40">标题</span>
              <input
                value={resourceForm.title}
                onChange={event => setResourceForm(prev => ({ ...prev, title: event.target.value }))}
                placeholder="例如：世界观核心设定"
                className="border border-foreground/15 bg-transparent px-4 py-3 text-base text-foreground/80 outline-none focus:border-foreground/30 font-newspaper placeholder:text-foreground/20"
              />
            </label>

            <div className="grid gap-1.5">
              <span className="text-xs font-newspaper text-foreground/40">类型</span>
              <div className="flex flex-wrap gap-2">
                {(Object.entries(resourceTypeConfig) as Array<[import('../../types').ResourceType, typeof resourceTypeConfig[import('../../types').ResourceType]]>).map(([type, cfg]) => (
                  <button
                    key={type}
                    onClick={() => setResourceForm(prev => ({ ...prev, type }))}
                    className={`border px-3 py-2 text-sm transition-all font-newspaper ${resourceForm.type === type ? 'border-foreground/30 bg-foreground/5 text-foreground/80' : 'border-foreground/15 bg-transparent text-foreground/40 hover:text-foreground/60'}`}
                  >
                    {cfg.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between border border-foreground/15 px-4 py-3">
              <div>
                <div className="text-sm font-newspaper-bold text-foreground/80">标记为必读资料</div>
                <div className="text-xs text-foreground/30 font-newspaper">后续可作为 Agent 默认上下文资料</div>
              </div>
              <Switch checked={resourceForm.is_required} onCheckedChange={checked => setResourceForm(prev => ({ ...prev, is_required: checked }))} />
            </div>

            <label className="grid gap-1.5">
              <span className="text-xs font-newspaper text-foreground/40">标签</span>
              <input
                value={resourceForm.tags}
                onChange={event => setResourceForm(prev => ({ ...prev, tags: event.target.value }))}
                placeholder="用逗号分隔，例如：世界观, 人物, 规则"
                className="border border-foreground/15 bg-transparent px-4 py-3 text-sm text-foreground/80 outline-none focus:border-foreground/30 font-newspaper placeholder:text-foreground/20"
              />
            </label>

            <label className="grid gap-1.5">
              <span className="text-xs font-newspaper text-foreground/40">Markdown 内容</span>
              <textarea
                value={resourceForm.content}
                onChange={event => setResourceForm(prev => ({ ...prev, content: event.target.value }))}
                rows={24}
                placeholder={'# 标题\n\n支持列表、表格、代码块、引用和链接。'}
                className="min-h-[520px] border border-foreground/15 bg-transparent px-4 py-4 font-mono text-sm leading-relaxed text-foreground/80 outline-none focus:border-foreground/30"
              />
            </label>
          </div>
        </div>
      </div>
    );
  }

  if (!selectedResource) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <FileTextIcon className="mx-auto mb-3 h-10 w-10 text-foreground/20" />
          <div className="text-sm font-newspaper-bold text-foreground/80">选择或新建一条资料</div>
          <div className="mt-1 text-xs text-foreground/30 font-newspaper">资料会直接占用对话主区域展示，不再挤在左侧小卡片里。</div>
          <button onClick={startCreateResource} className="mt-4 inline-flex items-center gap-2 border border-foreground/30 px-3 py-1.5 text-xs font-newspaper-bold text-foreground/60 hover:bg-foreground/5">
            <PlusIcon className="h-3.5 w-3.5" />
            新建资料
          </button>
        </div>
      </div>
    );
  }

  const cfg = resourceTypeConfig[selectedResource.type] || resourceTypeConfig.custom;
  const Icon = cfg.icon;
  const charCount = selectedResource.content.trim().length;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-foreground/15 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1 border border-foreground/20 px-2 py-0.5 text-[10px] font-newspaper-bold text-foreground/60">
                  <Icon className="h-3 w-3" />
                  {cfg.label}
                </span>
                {selectedResource.is_required && <span className="border border-foreground/30 px-2 py-0.5 text-[10px] font-newspaper-bold text-foreground/60">必读资料</span>}
                {(selectedResource.tags || []).map(tag => <span key={tag} className="border border-foreground/15 px-2 py-0.5 text-[10px] text-foreground/30 font-newspaper">#{tag}</span>)}
              </div>
              <h2 className="truncate text-lg font-newspaper-bold text-foreground/80">{selectedResource.title}</h2>
              <div className="mt-1 text-[10px] text-foreground/30 font-newspaper">更新于 {formatResourceDate(selectedResource.updated_at || selectedResource.created_at)}</div>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <button onClick={() => setMainMode('chat')} className="px-3 py-1.5 text-sm text-foreground/40 hover:bg-foreground/5 hover:text-foreground/80 font-newspaper">返回对话</button>
              <button onClick={startEditResource} className="flex items-center gap-1.5 border border-foreground/15 px-3 py-1.5 text-sm text-foreground/60 hover:bg-foreground/5 font-newspaper">
                <EditIcon className="h-4 w-4" />
                修改
              </button>
              <button onClick={() => setDeletingResource(selectedResource)} className="flex items-center gap-1.5 border border-foreground/15 px-3 py-1.5 text-sm text-foreground/60 hover:bg-foreground/5 font-newspaper">
                <TrashIcon className="h-4 w-4" />
                删除
              </button>
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {selectedResource.content_type === 'markdown' ? (
            <MarkdownRenderer content={selectedResource.content} className="mx-auto max-w-4xl" />
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
                return <div className="text-sm text-foreground/60">地图数据解析失败</div>;
              }
            })()
          ) : (
            (() => {
              try {
                const parsed = JSON.parse(selectedResource.content);
                const viewType = selectedResource.content_type as import('../../render-engine/types').ViewType;
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
                return <MarkdownRenderer content={selectedResource.content} className="mx-auto max-w-4xl" />;
              }
            })()
          )}
        </div>
      </div>

      <aside className="w-64 flex-shrink-0 border-l border-foreground/15 p-3">
        <div className="mb-4">
          <div className="mb-1.5 text-[10px] font-newspaper-bold uppercase tracking-wide text-foreground/40">资料目录</div>
          {resourceHeadings.length > 0 ? (
            <div className="flex flex-col gap-1">
              {resourceHeadings.map(heading => (
                <a key={heading.id} href={`#${heading.id}`} className={`px-2 py-1 text-xs text-foreground/40 hover:bg-foreground/5 hover:text-foreground/80 font-newspaper ${heading.level === 2 ? 'ml-3' : heading.level === 3 ? 'ml-6' : ''}`}>
                  {heading.text}
                </a>
              ))}
            </div>
          ) : (
            <div className="border border-dashed border-foreground/15 p-3 text-xs text-foreground/30 font-newspaper">添加 Markdown 标题后自动生成目录。</div>
          )}
        </div>
        <div className="mb-4 grid grid-cols-2 gap-1.5">
            <div className="border border-foreground/15 p-2">
              <div className="text-sm font-newspaper-bold text-foreground/80">{charCount}</div>
              <div className="text-[10px] text-foreground/30 font-newspaper">字符</div>
            </div>
            <div className="border border-foreground/15 p-2">
              <div className="text-sm font-newspaper-bold text-foreground/80">{resourceHeadings.length}</div>
              <div className="text-[10px] text-foreground/30 font-newspaper">标题</div>
            </div>
          </div>
          <div className="border border-dashed border-foreground/15 p-3">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-newspaper-bold text-foreground/80">
              <GitBranchIcon className="h-3.5 w-3.5 text-foreground/60" />
              知识图谱入口
            </div>
            <div className="text-[10px] leading-relaxed text-foreground/30 font-newspaper">后续可基于链接、标签和引用关系把资料串成图谱。</div>
        </div>
      </aside>
    </div>
  );
}
