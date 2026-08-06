import { Loader2Icon, AlertCircleIcon, InboxIcon, DatabaseIcon } from 'lucide-react';
import type { RenderSpec, ViewType } from './types';
import { useRenderData } from './useRenderData';
import { getViewComponent, registerView } from './registry';
import { cn } from '../lib/utils';

// 注册内置视图组件
import TableView from './views/TableView';
import ListView from './views/ListView';
import TreeView from './views/TreeView';
import DocumentView from './views/DocumentView';
import StatView from './views/StatView';
import CardView from './views/CardView';
import TimelineView from './views/TimelineView';
import MapView from './views/MapView';

registerView('table', TableView);
registerView('list', ListView);
registerView('tree', TreeView);
registerView('document', DocumentView);
registerView('stat', StatView);
registerView('card', CardView);
registerView('timeline', TimelineView);
registerView('map', MapView);

// ── 加载中 ──

function LoadingView({ text }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-12 text-muted-foreground">
      <Loader2Icon className="w-5 h-5 animate-spin mr-2" />
      <span className="text-sm">{text || '加载中...'}</span>
    </div>
  );
}

// ── 空数据 ──

function EmptyView({ text }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <InboxIcon className="w-8 h-8 mb-2 opacity-40" />
      <span className="text-sm">{text || '暂无数据'}</span>
    </div>
  );
}

// ── 错误 ──

function ErrorView({ error }: { error: Error }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
      <div className="flex items-center gap-2 mb-1">
        <AlertCircleIcon className="w-4 h-4" />
        <span className="font-medium">数据加载失败</span>
      </div>
      <p className="text-xs opacity-80">{error.message}</p>
    </div>
  );
}

// ── 不支持的视图类型 ──

function UnsupportedView({ viewType }: { viewType: string }) {
  return (
    <div className="border border-foreground/15 p-4 text-sm text-foreground/60 font-newspaper">
      <span>不支持的视图类型: {viewType}</span>
    </div>
  );
}

// ── 标题区 ──

function ViewTitle({ title, description, viewType }: { title?: string; description?: string; viewType?: string }) {
  if (!title && !description) return null;
  return (
    <div className="mb-3 flex items-start gap-2">
      <DatabaseIcon className="w-4 h-4 mt-0.5 text-primary/60 flex-shrink-0" />
      <div className="min-w-0">
        {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
    </div>
  );
}

// ── 主入口：RenderEngine ──

export interface RenderEngineProps {
  spec: RenderSpec;
  className?: string;
}

export default function RenderEngine({ spec, className }: RenderEngineProps) {
  const ViewComponent = getViewComponent(spec.view_type);

  // 如果有 data_source，加载远程数据；否则使用内联 data
  const { data, isLoading, error } = useRenderData(spec);

  // 不支持的视图类型
  if (!ViewComponent) {
    return (
      <div className={cn('render-engine rounded-lg border border-border/60 bg-muted/20 p-3', className)}>
        <ViewTitle title={spec.title} description={spec.description} viewType={spec.view_type} />
        <UnsupportedView viewType={spec.view_type} />
      </div>
    );
  }

  // 加载中
  if (isLoading) {
    return (
      <div className={cn('render-engine rounded-lg border border-border/60 bg-muted/20 p-3', className)}>
        <ViewTitle title={spec.title} description={spec.description} viewType={spec.view_type} />
        <LoadingView text={spec.options?.loading_text} />
      </div>
    );
  }

  // 错误
  if (error) {
    return (
      <div className={cn('render-engine rounded-lg border border-border/60 bg-muted/20 p-3', className)}>
        <ViewTitle title={spec.title} description={spec.description} viewType={spec.view_type} />
        <ErrorView error={error} />
      </div>
    );
  }

  // 无数据（但 map 等视图的数据在 options 中，不依赖 data 字段）
  if (data == null && spec.data == null && !spec.options?.map) {
    return (
      <div className={cn('render-engine rounded-lg border border-border/60 bg-muted/20 p-3', className)}>
        <ViewTitle title={spec.title} description={spec.description} viewType={spec.view_type} />
        <EmptyView text={spec.options?.empty_text} />
      </div>
    );
  }

  const resolvedData = data ?? spec.data;

  const isPopup = spec.style?.popup;

  return (
    <div
      className={cn(
        isPopup
          ? 'render-engine h-full overflow-hidden'
          : 'render-engine rounded-lg border border-primary/15 bg-primary/[0.03] p-3 overflow-hidden',
        !isPopup && spec.style?.bordered && 'border-border bg-card p-4',
        spec.style?.compact && 'text-xs',
        className,
      )}
      style={spec.style?.height ? { height: spec.style.height } : undefined}
    >
      {!isPopup && <ViewTitle title={spec.title} description={spec.description} viewType={spec.view_type} />}
      <ViewComponent
        data={resolvedData}
        options={spec.options}
        actions={spec.actions}
        style={spec.style}
      />
    </div>
  );
}

// 导出注册函数，供外部扩展自定义视图
export { registerView, getViewComponent } from './registry';
export type { RenderSpec, ViewType, ViewComponentProps } from './types';
