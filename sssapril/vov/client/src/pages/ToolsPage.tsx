import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeftIcon, WrenchIcon, SearchIcon, XIcon,
  FileCodeIcon, TerminalIcon, BrainIcon, ZapIcon, BotIcon,
  FolderIcon, MessageSquareIcon, CheckSquareIcon, PackageIcon,
  PaletteIcon, Loader2Icon,
} from 'lucide-react';
import { useToolCatalog, getToolsByCategory, type ToolCategory, type ToolCatalogItem, type CategoryLabel } from '../api/toolCatalog';

const categoryIcons: Record<string, typeof WrenchIcon> = {
  file: FileCodeIcon,
  shell: TerminalIcon,
  memory: BrainIcon,
  skill: ZapIcon,
  agent: BotIcon,
  project: FolderIcon,
  group: MessageSquareIcon,
  task: CheckSquareIcon,
  resource: PackageIcon,
  render: PaletteIcon,
};

function ToolDetailModal({ tool, categoryLabels, onClose }: { tool: ToolCatalogItem | null; categoryLabels: Record<string, CategoryLabel>; onClose: () => void }) {
  if (!tool) return null;
  const CatIcon = categoryIcons[tool.category] || WrenchIcon;
  const catInfo = categoryLabels[tool.category];

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-200 ${tool ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
      <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <div className={`relative newspaper-bg border border-foreground/20 w-[480px] max-h-[80vh] flex flex-col transition-all duration-200 ${tool ? 'scale-100' : 'scale-95'}`}>
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b border-foreground/15 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 border border-foreground/15 flex items-center justify-center">
              <CatIcon className="w-5 h-5 opacity-60" />
            </div>
            <div>
              <h2 className="text-base font-newspaper-bold">{tool.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                {catInfo && <span className="text-[10px] px-1.5 py-0.5 border border-foreground/15 opacity-60">{catInfo.label}</span>}
                <span className="text-[10px] opacity-40 font-mono">{tool.kind}</span>
                {tool.recommended && <span className="text-[10px] px-1.5 py-0.5 border border-foreground/20 opacity-60">推荐</span>}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="p-2 opacity-30 hover:opacity-70 transition-opacity">
            <XIcon className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
          <div>
            <span className="text-xs opacity-50 font-newspaper block mb-1">工具描述</span>
            <p className="text-sm opacity-80 leading-relaxed font-newspaper">{tool.description}</p>
          </div>

          {tool.detail && (
            <div>
              <span className="text-xs opacity-50 font-newspaper block mb-1">详细说明</span>
              <p className="text-xs opacity-40 leading-relaxed font-newspaper">{tool.detail}</p>
            </div>
          )}

          <div>
            <span className="text-xs opacity-50 font-newspaper block mb-2">工具标识</span>
            <code className="text-xs border border-foreground/10 px-2.5 py-1.5 font-mono opacity-70">{tool.kind}</code>
          </div>

          <div>
            <span className="text-xs opacity-50 font-newspaper block mb-2">工具类型</span>
            <span className="text-xs border border-foreground/15 px-2.5 py-1 opacity-60">内置 (builtin)</span>
          </div>

          {tool.params.length > 0 && (
            <div>
              <span className="text-xs opacity-50 font-newspaper block mb-2">可配置参数</span>
              <div className="flex flex-col gap-2">
                {tool.params.map(p => (
                  <div key={p.key} className="flex items-start gap-3 p-2.5 border border-foreground/10">
                    <code className="text-xs font-mono opacity-60 border border-foreground/10 px-1.5 py-0.5 flex-shrink-0">{p.key}</code>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium opacity-80">{p.label}</span>
                        <span className="text-[10px] opacity-40">{p.type}</span>
                        {p.required && <span className="text-[10px] opacity-70 font-newspaper-bold">必填</span>}
                      </div>
                      {p.placeholder && <p className="text-[11px] opacity-30 mt-0.5">{p.placeholder}</p>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ToolsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<ToolCategory | 'all'>('all');
  const [selectedTool, setSelectedTool] = useState<ToolCatalogItem | null>(null);

  const { data: catalogData, isLoading } = useToolCatalog();
  const tools = catalogData?.tools ?? [];
  const categoryLabels = catalogData?.categories ?? {};

  const grouped = useMemo(() => getToolsByCategory(tools), [tools]);
  const categories = useMemo(() => Array.from(grouped.keys()) as ToolCategory[], [grouped]);

  const filtered = useMemo(() => {
    let items = tools;
    if (selectedCategory !== 'all') {
      items = items.filter(t => t.category === selectedCategory);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(t =>
        t.name.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        t.kind.toLowerCase().includes(q)
      );
    }
    return items;
  }, [search, selectedCategory, tools]);

  const filteredGrouped = useMemo(() => {
    const map = new Map<ToolCategory, ToolCatalogItem[]>();
    for (const tool of filtered) {
      if (!map.has(tool.category)) map.set(tool.category, []);
      map.get(tool.category)!.push(tool);
    }
    return map;
  }, [filtered]);

  if (isLoading) {
    return (
      <div className="min-h-screen newspaper-bg flex items-center justify-center">
        <Loader2Icon className="w-6 h-6 animate-spin opacity-40" />
      </div>
    );
  }

  return (
    <div data-cmp="ToolsPage" className="min-h-screen newspaper-bg font-newspaper">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12 py-6 md:py-10">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <button onClick={() => navigate('/')} className="flex items-center gap-1.5 text-sm opacity-40 hover:opacity-80 transition-opacity">
            <ArrowLeftIcon className="w-4 h-4" />返回首页
          </button>
        </div>
        <div className="flex items-end justify-between mb-10">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 border border-foreground/20 flex items-center justify-center">
                <WrenchIcon className="w-5 h-5 opacity-60" />
              </div>
              <span className="text-xl font-newspaper-bold tracking-tight opacity-80">Agent 世界</span>
            </div>
            <h1 className="text-3xl font-newspaper-bold mb-1">工具库</h1>
            <p className="opacity-50 text-sm">浏览所有可用的内置工具，了解其功能和配置</p>
          </div>
          <div className="text-sm opacity-50">
            共 <span className="font-newspaper-bold">{tools.length}</span> 个工具
          </div>
        </div>

        <div className="h-px bg-foreground/20 mb-6" />

        {/* Search + Category filter */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <SearchIcon className="absolute left-0 top-1/2 -translate-y-1/2 w-4 h-4 opacity-30" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索工具..."
              className="w-full pl-7 pr-4 py-2 border-b border-foreground/20 bg-transparent text-sm font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/50 transition-colors" />
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            <button onClick={() => setSelectedCategory('all')}
              className={`px-3 py-1.5 text-xs transition-all border border-foreground/15 ${selectedCategory === 'all' ? 'font-newspaper-bold border-b-2 border-b-foreground/60' : 'opacity-40 hover:opacity-70'}`}>
              全部
            </button>
            {categories.map(cat => {
              const info = categoryLabels[cat];
              if (!info) return null;
              return (
                <button key={cat} onClick={() => setSelectedCategory(cat)}
                  className={`flex items-center gap-1 px-3 py-1.5 text-xs transition-all border border-foreground/15 ${selectedCategory === cat ? 'font-newspaper-bold border-b-2 border-b-foreground/60' : 'opacity-40 hover:opacity-70'}`}>
                  <span>{info.icon}</span>{info.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Tool grid grouped by category */}
        {filteredGrouped.size === 0 ? (
          <div className="text-center py-20">
            <p className="opacity-40">未找到匹配的工具</p>
          </div>
        ) : (
          <div className="flex flex-col gap-8">
            {Array.from(filteredGrouped.entries()).map(([cat, catTools]) => {
              const info = categoryLabels[cat];
              const CatIcon = categoryIcons[cat] || WrenchIcon;
              return (
                <div key={cat}>
                  <div className="flex items-center gap-2 mb-4">
                    <CatIcon className="w-4 h-4 opacity-50" />
                    <h2 className="text-sm font-newspaper-bold opacity-80">{info?.label || cat}</h2>
                    <span className="text-xs opacity-30">({catTools.length})</span>
                  </div>
                  <div className="h-px bg-foreground/15 mb-4" />
                  <div className="grid grid-cols-4 gap-4">
                    {catTools.map(tool => (
                      <button
                        key={tool.kind}
                        onClick={() => setSelectedTool(tool)}
                        className="border border-foreground/15 p-4 hover:border-foreground/30 transition-all duration-150 text-left group"
                      >
                        <div className="flex items-start justify-between mb-2">
                          <div className="w-8 h-8 border border-foreground/15 flex items-center justify-center">
                            <CatIcon className="w-4 h-4 opacity-50" />
                          </div>
                          {tool.recommended && (
                            <span className="text-[9px] px-1 py-0.5 border border-foreground/20 opacity-50">推荐</span>
                          )}
                        </div>
                        <h3 className="text-sm font-medium opacity-80 group-hover:opacity-100 transition-opacity mb-1 font-newspaper">{tool.name}</h3>
                        <p className="text-xs opacity-40 leading-relaxed line-clamp-2 mb-2 font-newspaper">{tool.description}</p>
                        <code className="text-[10px] opacity-25 font-mono">{tool.kind}</code>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ToolDetailModal tool={selectedTool} categoryLabels={categoryLabels} onClose={() => setSelectedTool(null)} />
    </div>
  );
}
