import { BotIcon, ChevronDownIcon, ChevronRightIcon, FileTextIcon, FolderIcon, MessageSquareIcon, PackageIcon, SparklesIcon } from 'lucide-react';
import { getNodeSelectionState, toggleTreeNode, type ProjectTreeNode, type TreeSelection } from '../../lib/projectContentTree';

interface ProjectContentTreeProps {
  nodes: ProjectTreeNode[];
  mode?: 'view' | 'select';
  selection?: TreeSelection;
  expanded: Record<string, boolean>;
  onExpandedChange: (expanded: Record<string, boolean>) => void;
  onSelectionChange?: (selection: TreeSelection) => void;
  onNodeClick?: (node: ProjectTreeNode) => void;
}

const iconMap = {
  project: PackageIcon,
  section: FolderIcon,
  agent: BotIcon,
  skill: SparklesIcon,
  group: MessageSquareIcon,
  task: FileTextIcon,
  'resource-type': FolderIcon,
  resource: FileTextIcon,
  deliverable: FileTextIcon,
  messages: MessageSquareIcon,
};

export default function ProjectContentTree({
  nodes,
  mode = 'view',
  selection = {},
  expanded,
  onExpandedChange,
  onSelectionChange,
  onNodeClick,
}: ProjectContentTreeProps) {
  const toggleExpanded = (id: string) => {
    onExpandedChange({ ...expanded, [id]: !expanded[id] });
  };

  const toggleSelection = (id: string) => {
    onSelectionChange?.(toggleTreeNode(nodes, selection, id));
  };

  return (
    <div className="rounded-3xl border border-border bg-card p-3 shadow-custom">
      {nodes.map(node => (
        <TreeNodeRow
          key={node.id}
          node={node}
          depth={0}
          mode={mode}
          rootNodes={nodes}
          selection={selection}
          expanded={expanded}
          onToggleExpanded={toggleExpanded}
          onToggleSelection={toggleSelection}
          onNodeClick={onNodeClick}
        />
      ))}
    </div>
  );
}

interface TreeNodeRowProps {
  node: ProjectTreeNode;
  depth: number;
  mode: 'view' | 'select';
  rootNodes: ProjectTreeNode[];
  selection: TreeSelection;
  expanded: Record<string, boolean>;
  onToggleExpanded: (id: string) => void;
  onToggleSelection: (id: string) => void;
  onNodeClick?: (node: ProjectTreeNode) => void;
}

function TreeNodeRow({
  node,
  depth,
  mode,
  rootNodes,
  selection,
  expanded,
  onToggleExpanded,
  onToggleSelection,
  onNodeClick,
}: TreeNodeRowProps) {
  const hasChildren = !!node.children?.length;
  const isExpanded = expanded[node.id] ?? depth < 2;
  const state = getNodeSelectionState(node, selection);
  const Icon = iconMap[node.kind] || FileTextIcon;

  return (
    <div>
      <div
        className="group flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-accent/60 transition-colors"
        style={{ paddingLeft: `${depth * 18 + 8}px` }}
      >
        <button
          onClick={() => hasChildren && onToggleExpanded(node.id)}
          className="flex h-5 w-5 items-center justify-center rounded-md text-muted-foreground hover:bg-background disabled:opacity-30"
          disabled={!hasChildren}
        >
          {hasChildren ? (isExpanded ? <ChevronDownIcon className="w-4 h-4" /> : <ChevronRightIcon className="w-4 h-4" />) : null}
        </button>

        {mode === 'select' && (
          <button
            onClick={() => onToggleSelection(node.id)}
            className={`flex h-4 w-4 items-center justify-center rounded border text-[10px] ${state === 'checked' ? 'border-primary bg-primary text-primary-foreground' : state === 'partial' ? 'border-primary bg-primary/20 text-primary' : 'border-border bg-background'}`}
          >
            {state === 'checked' ? '✓' : state === 'partial' ? '—' : ''}
          </button>
        )}

        <button
          onClick={() => onNodeClick?.(node)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <Icon className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-foreground">{node.label}</span>
              {node.badge && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{node.badge}</span>}
            </div>
            {node.description && <p className="truncate text-xs text-muted-foreground">{node.description}</p>}
          </div>
        </button>
      </div>

      {hasChildren && isExpanded && (
        <div>
          {node.children!.map(child => (
            <TreeNodeRow
              key={child.id}
              node={child}
              depth={depth + 1}
              mode={mode}
              rootNodes={rootNodes}
              selection={selection}
              expanded={expanded}
              onToggleExpanded={onToggleExpanded}
              onToggleSelection={onToggleSelection}
              onNodeClick={onNodeClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}
