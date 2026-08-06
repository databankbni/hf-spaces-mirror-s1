import { useState } from 'react';
import {
  ChevronDownIcon,
  ChevronRightIcon,
  FileTextIcon,
  FolderIcon,
  BotIcon,
  PackageIcon,
  SparklesIcon,
  MessageSquareIcon,
} from 'lucide-react';
import type { ViewComponentProps } from '../types';

const defaultIconMap: Record<string, typeof FileTextIcon> = {
  project: PackageIcon,
  section: FolderIcon,
  folder: FolderIcon,
  agent: BotIcon,
  skill: SparklesIcon,
  group: MessageSquareIcon,
  task: FileTextIcon,
  resource: FileTextIcon,
  deliverable: FileTextIcon,
  messages: MessageSquareIcon,
};

interface TreeNode {
  id?: string;
  kind?: string;
  label?: string;
  name?: string;
  title?: string;
  description?: string;
  badge?: string;
  children?: TreeNode[];
  [key: string]: unknown;
}

export default function TreeView({ data, options }: ViewComponentProps) {
  const nodes = normalizeTreeNodes(data, options);
  const defaultDepth = options?.default_expand_depth ?? 2;
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    nodes.forEach(n => init[n.id] = true);
    return init;
  });

  const toggleExpand = (id: string) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }));
  };

  if (nodes.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无数据'}</div>;
  }

  return (
    <div className="rounded-xl border border-border bg-card p-3">
      {nodes.map(node => (
        <TreeNodeRow
          key={node.id}
          node={node}
          depth={0}
          expanded={expanded}
          defaultDepth={defaultDepth}
          iconMap={options?.icon_map}
          onToggle={toggleExpand}
        />
      ))}
    </div>
  );
}

function normalizeTreeNodes(data: unknown, options?: ViewComponentProps['options']): TreeNode[] {
  if (Array.isArray(data)) return data.map((item, _i) => normalizeNode(item));
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    // 如果对象有 children 字段，视为单根树
    const childrenField = options?.children_field || 'children';
    if (obj[childrenField]) {
      return [normalizeNode(obj)];
    }
    // 否则把每个值作为子节点
    return Object.entries(obj).map(([key, value]) => normalizeNode(value, key));
  }
  return [];
}

function normalizeNode(item: unknown, fallbackLabel?: string): TreeNode {
  if (!item || typeof item !== 'object') {
    return { id: String(fallbackLabel ?? Math.random()), label: String(item ?? fallbackLabel ?? '') };
  }
  const obj = item as Record<string, unknown>;
  return {
    ...obj,
    id: String(obj.id ?? fallbackLabel ?? Math.random()),
    kind: obj.kind as string | undefined,
    label: (obj.label || obj.name || obj.title || fallbackLabel) as string | undefined,
    description: obj.description as string | undefined,
    badge: obj.badge as string | undefined,
    children: Array.isArray(obj.children) ? (obj.children as unknown[]).map((c: unknown) => normalizeNode(c)) : undefined,
  };
}

function TreeNodeRow({
  node,
  depth,
  expanded,
  defaultDepth,
  iconMap,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  expanded: Record<string, boolean>;
  defaultDepth: number;
  iconMap?: Record<string, string>;
  onToggle: (id: string) => void;
}) {
  const hasChildren = !!node.children?.length;
  const isExpanded = expanded[node.id!] ?? depth < defaultDepth;
  const kind = node.kind || 'default';
  const IconComp = defaultIconMap[iconMap?.[kind] ?? kind] || FileTextIcon;

  return (
    <div>
      <div
        className="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-accent/60 transition-colors"
        style={{ paddingLeft: `${depth * 18 + 8}px` }}
      >
        <button
          onClick={() => hasChildren && onToggle(node.id!)}
          className="flex h-5 w-5 items-center justify-center rounded-md text-muted-foreground hover:bg-background disabled:opacity-30"
          disabled={!hasChildren}
        >
          {hasChildren ? (isExpanded ? <ChevronDownIcon className="w-3.5 h-3.5" /> : <ChevronRightIcon className="w-3.5 h-3.5" />) : null}
        </button>
        <IconComp className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-foreground">{node.label}</span>
            {node.badge && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{node.badge}</span>}
          </div>
          {node.description && <p className="truncate text-xs text-muted-foreground">{node.description}</p>}
        </div>
      </div>
      {hasChildren && isExpanded && (
        <div>
          {node.children!.map(child => (
            <TreeNodeRow
              key={child.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              defaultDepth={defaultDepth}
              iconMap={iconMap}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}
