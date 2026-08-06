import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PlusIcon, BotIcon, SearchIcon,
  XIcon, EditIcon, TrashIcon,
  CheckIcon,
  DownloadIcon, UploadIcon, ArrowLeftIcon,
} from 'lucide-react';
import { useAgents, useAgent, useCreateAgent, useUpdateAgent, useDeleteAgent } from '../hooks/useAgents';
import { useSkills } from '../hooks/useSkills';
import { useExportableAgents, useExportDownload, useImportPreview, useImportExecute } from '../hooks/useExportImport';
import AgentCard from '../components/AgentCard';
import ExportDialog from '../components/ExportDialog';
import ImportDialog from '../components/ImportDialog';
import SkeletonCard from '../components/SkeletonCard';
import type { Agent, Skill, CreateAgentRequest, UpdateAgentRequest } from '../types/agent';
import type { ExportRequestItem, ConflictResolution } from '../types';
import { useToolCatalog, getToolsByCategory, type ToolCategory, type ToolCatalogItem, type CategoryLabel } from '../api/toolCatalog';

/* ---------- 工具目录选择器组件 ---------- */

function ToolPicker({
  selectedKinds,
  onToggle,
  searchQuery,
  onSearchChange,
  tools,
  categoryLabels,
}: {
  selectedKinds: Set<string>;
  onToggle: (kind: string) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  tools: ToolCatalogItem[];
  categoryLabels: Record<string, CategoryLabel>;
}) {
  const grouped = useMemo(() => getToolsByCategory(tools), [tools]);

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return grouped;
    const q = searchQuery.toLowerCase();
    const result = new Map<ToolCategory, ToolCatalogItem[]>();
    for (const [cat, tools] of grouped) {
      const matched = tools.filter(
        t => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q) || t.kind.toLowerCase().includes(q)
      );
      if (matched.length > 0) result.set(cat, matched);
    }
    return result;
  }, [grouped, searchQuery]);

  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-foreground/40" />
        <input
          value={searchQuery}
          onChange={e => onSearchChange(e.target.value)}
          placeholder="搜索工具..."
          className="w-full pl-8 pr-3 py-1.5 border border-foreground/15 text-xs font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30"
        />
      </div>
      <div className="max-h-[420px] overflow-y-auto flex flex-col gap-2 pr-1">
        {Array.from(filtered.entries()).map(([cat, tools]) => (
          <div key={cat}>
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-sm">{categoryLabels[cat].icon}</span>
              <span className="text-xs font-newspaper-bold text-foreground/80">{categoryLabels[cat].label}</span>
              <span className="text-[10px] font-newspaper text-foreground/40">({tools.filter(t => selectedKinds.has(t.kind)).length}/{tools.length})</span>
            </div>
            <div className="flex flex-col gap-1">
              {tools.map(tool => {
                const selected = selectedKinds.has(tool.kind);
                return (
                  <button
                    key={tool.kind}
                    onClick={() => onToggle(tool.kind)}
                    className={`flex items-start gap-2.5 p-2 text-left transition-all border border-foreground/15 ${
                      selected
                        ? 'border-foreground/30'
                        : 'hover:border-foreground/20'
                    }`}
                  >
                    <div className={`w-4 h-4 mt-0.5 flex-shrink-0 flex items-center justify-center transition-colors border ${
                      selected ? 'border-foreground/60 text-foreground/80' : 'border-foreground/30'
                    }`}>
                      {selected && <CheckIcon className="w-3 h-3" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-newspaper-bold text-foreground">{tool.name}</span>
                        {tool.recommended && !selected && (
                          <span className="text-[9px] font-newspaper-bold opacity-60">推荐</span>
                        )}
                      </div>
                      <p className="text-[11px] font-newspaper text-foreground/40 leading-snug line-clamp-2">{tool.description}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {filtered.size === 0 && (
          <p className="text-xs font-newspaper text-foreground/40 text-center py-4">未找到匹配的工具</p>
        )}
      </div>
    </div>
  );
}

/* ---------- 技能选择器组件 ---------- */

function SkillPicker({
  selectedIds,
  onToggle,
  searchQuery,
  onSearchChange,
}: {
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
}) {
  const { data: skillsData, isLoading } = useSkills();
  const allSkills: Skill[] = skillsData?.items || [];

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return allSkills;
    const q = searchQuery.toLowerCase();
    return allSkills.filter(s =>
      s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
    );
  }, [allSkills, searchQuery]);

  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-foreground/40" />
        <input
          value={searchQuery}
          onChange={e => onSearchChange(e.target.value)}
          placeholder="搜索技能..."
          className="w-full pl-8 pr-3 py-1.5 border border-foreground/15 text-xs font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30"
        />
      </div>
      <div className="max-h-[420px] overflow-y-auto flex flex-col gap-1 pr-1">
        {isLoading && <p className="text-xs font-newspaper text-foreground/40 text-center py-2">加载中...</p>}
        {!isLoading && filtered.length === 0 && (
          <p className="text-xs font-newspaper text-foreground/40 text-center py-2">暂无技能，去技能库创建</p>
        )}
        {filtered.map(skill => {
          const selected = selectedIds.has(skill.id);
          return (
            <button
              key={skill.id}
              onClick={() => onToggle(skill.id)}
              className={`flex items-start gap-2.5 p-2 text-left transition-all border border-foreground/15 ${
                selected ? 'border-foreground/30' : 'hover:border-foreground/20'
              }`}
            >
              <div className={`w-4 h-4 mt-0.5 flex-shrink-0 flex items-center justify-center transition-colors border ${
                selected ? 'border-foreground/60 text-foreground/80' : 'border-foreground/30'
              }`}>
                {selected && <CheckIcon className="w-3 h-3" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-newspaper-bold text-foreground">{skill.name}</span>
                  <span className="text-[10px] font-newspaper opacity-50">{skill.skill_type}</span>
                </div>
                {skill.description && <p className="text-[11px] font-newspaper text-foreground/40 leading-snug line-clamp-2">{skill.description}</p>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- 全屏 Agent 编辑器（编辑桌 / Editorial Desk）---------- */

interface AgentEditorProps {
  initial: Agent | null;
  onClose: () => void;
  onSave: (data: CreateAgentRequest | UpdateAgentRequest) => Promise<void>;
  isPending?: boolean;
}

const PROMPT_MIN_H = 480;

function todayDateline(): string {
  const d = new Date();
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}

function AgentEditor({ initial, onClose, onSave, isPending }: AgentEditorProps) {
  const isEdit = !!initial;
  const { data: catalogData } = useToolCatalog();
  const catalogTools = catalogData?.tools ?? [];
  const catalogCategoryLabels = catalogData?.categories ?? {};

  // 用 useState 初始化器从 initial 派生初值；父级用 key 重挂载，避免 setState 副作用
  const [name, setName] = useState(initial?.name || '');
  const [description, setDescription] = useState(initial?.description || '');
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt || '');
  const [avatar, setAvatar] = useState(initial?.avatar || '🤖');
  const [capabilities, setCapabilities] = useState(initial?.capabilities?.join(', ') || '');
  const [model, setModel] = useState(initial?.llm_config?.model || '');
  const [temperature, setTemperature] = useState(String(initial?.llm_config?.temperature ?? ''));
  const [maxTokens, setMaxTokens] = useState(String(initial?.llm_config?.max_tokens ?? ''));
  const [selectedToolKinds, setSelectedToolKinds] = useState<Set<string>>(
    new Set(initial?.tools?.map(t => t.kind || (t.config as Record<string, unknown>)?.kind as string || t.name) || [])
  );
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(
    new Set(initial?.skills?.map(s => s.id) || [])
  );
  const [toolSearch, setToolSearch] = useState('');
  const [skillSearch, setSkillSearch] = useState('');

  const toggleTool = (kind: string) => {
    setSelectedToolKinds(prev => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  const toggleSkill = (id: string) => {
    setSelectedSkillIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (!name.trim() || !systemPrompt.trim()) return;
    const llmConfig: Record<string, unknown> = {};
    if (model.trim()) llmConfig.model = model.trim();
    if (temperature !== '' && !isNaN(Number(temperature))) llmConfig.temperature = Number(temperature);
    if (maxTokens !== '' && !isNaN(Number(maxTokens))) llmConfig.max_tokens = Number(maxTokens);

    const data: any = {
      name: name.trim(),
      description: description.trim() || undefined,
      system_prompt: systemPrompt.trim(),
      avatar,
      capabilities: capabilities.split(',').map(s => s.trim()).filter(Boolean),
      llm_config: Object.keys(llmConfig).length > 0 ? llmConfig : undefined,
    };

    const hasToolChanges = selectedToolKinds.size > 0 || (isEdit && (initial?.tools?.length || 0) > 0);
    if (hasToolChanges) {
      data.tools = Array.from(selectedToolKinds).map(kind => {
        const catalogItem = catalogTools.find(t => t.kind === kind);
        return {
          name: kind,
          kind,
          description: catalogItem?.description || kind,
          tool_type: 'builtin',
          config: {},
        };
      });
    }

    const hasSkillChanges = selectedSkillIds.size > 0 || (isEdit && (initial?.skills?.length || 0) > 0);
    if (hasSkillChanges) {
      data.skill_ids = Array.from(selectedSkillIds);
    }

    await onSave(data);
  };

  // Cmd/Ctrl+S 快捷保存
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        handleSubmit();
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleSubmit, onClose]);

  // 系统提示词：自动撑高（min 480px, max 70vh）
  const promptRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = promptRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const max = Math.floor(window.innerHeight * 0.7);
    const h = Math.min(Math.max(el.scrollHeight, PROMPT_MIN_H), max);
    el.style.height = h + 'px';
  }, [systemPrompt]);

  const promptChars = systemPrompt.length;
  const promptLines = systemPrompt ? systemPrompt.split('\n').length : 0;
  const canSave = !!name.trim() && !!systemPrompt.trim() && !isPending;

  return (
    <div className="fixed inset-0 z-50 newspaper-bg flex flex-col animate-in fade-in duration-200">
      {/* 报头 Masthead */}
      <header className="border-b-2 border-double border-foreground/30 flex-shrink-0 bg-background/40">
        <div className="px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <button onClick={onClose}
              className="group flex items-center gap-1.5 text-xs font-newspaper text-foreground/50 hover:text-foreground transition-colors">
              <ArrowLeftIcon className="w-3.5 h-3.5 group-hover:-translate-x-0.5 transition-transform" />
              <span>Agent 库</span>
            </button>
            <div className="h-5 w-px bg-foreground/20" />
            <div>
              <div className="text-[10px] font-newspaper-bold uppercase tracking-[0.3em] text-foreground/40 leading-none">
                DRAFT · {todayDateline()}
              </div>
              <h1 className="text-xl font-newspaper-bold text-foreground mt-0.5 leading-tight">
                {isEdit ? `编辑 · ${initial?.name}` : '新建档案 · Agent'}
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-6">
            {isPending && (
              <span className="text-xs font-newspaper italic text-foreground/40">保存中…</span>
            )}
            <button onClick={onClose}
              className="text-sm font-newspaper text-foreground/60 hover:text-foreground hover:underline transition-colors">
              取消
            </button>
            <button onClick={handleSubmit} disabled={!canSave}
              className="text-sm font-newspaper-bold text-foreground/90 hover:text-foreground hover:underline transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:no-underline">
              {isEdit ? '保存修改' : '归档发布'}
            </button>
            <button onClick={onClose}
              className="ml-2 p-1.5 text-foreground/40 hover:text-foreground hover:bg-foreground/5 transition-colors"
              title="关闭 (Esc)">
              <XIcon className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* 主体：中央稿 + 右侧简报 */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_380px] overflow-hidden">
        {/* 中央：Manuscrip */}
        <main className="overflow-y-auto bg-background/30">
          <div className="max-w-[860px] mx-auto px-10 md:px-14 py-10 md:py-12 flex flex-col gap-10">

            {/* 基础信息 */}
            <EditorialSection kicker="THE BASICS · 第一部分" title="基础信息">
              <div className="flex gap-5">
                <div className="w-24 h-24 border border-foreground/20 flex items-center justify-center text-5xl flex-shrink-0 bg-foreground/5">
                  {avatar || '🤖'}
                </div>
                <div className="flex-1 flex flex-col gap-3">
                  <div>
                    <FieldLabel>名称 *</FieldLabel>
                    <input value={name} onChange={e => setName(e.target.value)} placeholder="给 Agent 起个名字"
                      className="w-full px-4 py-2.5 border border-foreground/15 text-base font-newspaper-bold text-foreground placeholder:text-foreground/30 placeholder:font-newspaper focus:outline-none focus:border-foreground/40 transition-colors" />
                  </div>
                  <div>
                    <FieldLabel>头像 (emoji)</FieldLabel>
                    <input value={avatar} onChange={e => setAvatar(e.target.value)} placeholder="🤖"
                      className="w-full px-4 py-2 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors" />
                  </div>
                </div>
              </div>

              <div>
                <FieldLabel>摘要 / Description</FieldLabel>
                <textarea value={description} onChange={e => setDescription(e.target.value)}
                  placeholder="一句话概括这个 Agent 的定位与擅长领域"
                  rows={2}
                  className="w-full px-4 py-2.5 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors resize-none" />
              </div>
            </EditorialSection>

            {/* 系统提示词 - Hero */}
            <EditorialSection
              kicker="THE MANUSCRIPT · 正文"
              title="系统提示词 *"
              annotation={`${promptChars.toLocaleString()} 字 · ${promptLines} 行`}
            >
              <textarea
                ref={promptRef}
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Tab') {
                    e.preventDefault();
                    const el = e.currentTarget;
                    const start = el.selectionStart;
                    const end = el.selectionEnd;
                    const newVal = el.value.substring(0, start) + '  ' + el.value.substring(end);
                    setSystemPrompt(newVal);
                    requestAnimationFrame(() => {
                      el.selectionStart = el.selectionEnd = start + 2;
                    });
                  }
                }}
                placeholder="定义这个 Agent 的角色、语气、行为准则、约束条件和擅长场景…&#10;&#10;可以是几行简短指令，也可以是结构化的大段设定。&#10;&#10;提示：Tab 插入缩进 · Cmd/Ctrl+S 保存"
                rows={12}
                style={{ minHeight: PROMPT_MIN_H }}
                className="w-full px-5 py-4 border border-foreground/20 bg-background/50 text-sm font-mono text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/50 transition-colors resize-none leading-relaxed"
              />
            </EditorialSection>

            {/* 能力标签 */}
            <EditorialSection kicker="THE TAGS · 索引" title="能力标签">
              <input value={capabilities} onChange={e => setCapabilities(e.target.value)}
                placeholder="用逗号分隔，如：长文写作, 观点分析, 风格模仿"
                className="w-full px-4 py-2.5 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors" />
              {capabilities.trim() && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {capabilities.split(',').map(s => s.trim()).filter(Boolean).map(tag => (
                    <span key={tag} className="text-[11px] font-newspaper px-2 py-0.5 border border-foreground/20 text-foreground/70">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </EditorialSection>
          </div>
        </main>

        {/* 右侧：The Brief */}
        <aside className="border-l border-foreground/15 overflow-y-auto bg-background/50">
          <div className="px-7 py-10 flex flex-col gap-8">

            {/* 模型配置 */}
            <EditorialSection kicker="THE MODEL · 模型" title="配置" compact>
              <div className="flex flex-col gap-3">
                <div>
                  <FieldLabel>模型</FieldLabel>
                  <input value={model} onChange={e => setModel(e.target.value)} placeholder="如 gpt-4o, claude-3.5-sonnet"
                    className="w-full px-3 py-2 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <FieldLabel>温度</FieldLabel>
                    <input value={temperature} onChange={e => setTemperature(e.target.value)} placeholder="0-2"
                      className="w-full px-3 py-2 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors" />
                  </div>
                  <div>
                    <FieldLabel>最大 Token</FieldLabel>
                    <input value={maxTokens} onChange={e => setMaxTokens(e.target.value)} placeholder="如 4096"
                      className="w-full px-3 py-2 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30 transition-colors" />
                  </div>
                </div>
              </div>
            </EditorialSection>

            {/* 工具 */}
            <EditorialSection
              kicker="THE TOOLS · 工具"
              title={selectedToolKinds.size > 0 ? `已装备 ${selectedToolKinds.size} 件` : '可用工具'}
              compact
            >
              <ToolPicker
                selectedKinds={selectedToolKinds}
                onToggle={toggleTool}
                searchQuery={toolSearch}
                onSearchChange={setToolSearch}
                tools={catalogTools}
                categoryLabels={catalogCategoryLabels}
              />
            </EditorialSection>

            {/* 技能 */}
            <EditorialSection
              kicker="THE SKILLS · 技能"
              title={selectedSkillIds.size > 0 ? `已装载 ${selectedSkillIds.size} 项` : '可用技能'}
              compact
            >
              <SkillPicker
                selectedIds={selectedSkillIds}
                onToggle={toggleSkill}
                searchQuery={skillSearch}
                onSearchChange={setSkillSearch}
              />
            </EditorialSection>
          </div>
        </aside>
      </div>

      {/* 状态栏 Status Bar */}
      <footer className="border-t border-foreground/15 px-8 py-2 flex items-center justify-between text-[10px] font-newspaper text-foreground/50 flex-shrink-0 bg-background/40">
        <div className="flex items-center gap-4">
          <span><kbd className="px-1 border border-foreground/20">Tab</kbd> 缩进</span>
          <span><kbd className="px-1 border border-foreground/20">⌘/Ctrl + S</kbd> 保存</span>
          <span><kbd className="px-1 border border-foreground/20">Esc</kbd> 关闭</span>
        </div>
        <div className="flex items-center gap-4">
          {isEdit && initial?.id && <span>ID · {initial.id.slice(0, 8)}</span>}
          <span>系统提示词 · {promptChars.toLocaleString()} 字 · {promptLines} 行</span>
        </div>
      </footer>
    </div>
  );
}

/* ---------- 编辑型小工具 ---------- */

function EditorialSection({
  kicker,
  title,
  annotation,
  compact = false,
  children,
}: {
  kicker: string;
  title: string;
  annotation?: string;
  compact?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className={`${compact ? 'mb-3' : 'mb-5'} pb-2.5 border-b border-foreground/20`}>
        <div className="text-[10px] font-newspaper-bold uppercase tracking-[0.28em] text-foreground/40 leading-none mb-1.5">
          {kicker}
        </div>
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-base md:text-lg font-newspaper-bold text-foreground leading-tight">
            {title}
          </h2>
          {annotation && (
            <span className="text-[11px] font-newspaper text-foreground/45 whitespace-nowrap">
              {annotation}
            </span>
          )}
        </div>
      </header>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-[10px] font-newspaper-bold text-foreground/45 uppercase tracking-[0.2em] mb-1.5 block">
      {children}
    </label>
  );
}


/* ---------- 主页面 ---------- */

export default function AgentsPage() {
  const navigate = useNavigate();
  const { data: agentsData, isLoading, refetch } = useAgents();
  const deleteMutation = useDeleteAgent();
  const createMutation = useCreateAgent();
  const updateMutation = useUpdateAgent();

  const [search, setSearch] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  // 全屏编辑器：单一状态 + nonce 让 React 在每次"新建"时重挂载编辑器
  type EditorState =
    | { kind: 'create'; nonce: number }
    | { kind: 'edit'; agent: Agent };
  const [editing, setEditing] = useState<EditorState | null>(null);

  // 导出导入
  const [exportOpen, setExportOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const { data: exportableAgents, isLoading: exportLoading } = useExportableAgents();
  const exportDownload = useExportDownload();
  const importPreview = useImportPreview();
  const importExecute = useImportExecute();

  const { data: agentDetail } = useAgent(selectedAgent?.id || '');

  const agents = agentsData?.items || [];
  const filtered = agents.filter((a: any) =>
    !search || a.name.toLowerCase().includes(search.toLowerCase()) || a.description?.toLowerCase().includes(search.toLowerCase())
  );

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm('确定删除此 Agent？')) return;
    await deleteMutation.mutateAsync(id);
    refetch();
  };

  const handleSave = async (data: CreateAgentRequest | UpdateAgentRequest) => {
    if (editing?.kind === 'create') {
      await createMutation.mutateAsync(data as CreateAgentRequest);
    } else if (editing?.kind === 'edit') {
      await updateMutation.mutateAsync({ id: editing.agent.id, data });
      // 如果当前在查看此 Agent 的卡片，同步更新它
      setSelectedAgent(prev => prev && prev.id === editing.agent.id ? { ...prev, ...data } as Agent : prev);
    }
    await refetch();
    setEditing(null);
  };

  const displayAgent = agentDetail || selectedAgent;

  return (
    <div data-cmp="AgentsPage" className="min-h-screen newspaper-bg">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12 py-6 md:py-10">
        {/* Newspaper Masthead Header */}
        <div className="mb-8 md:mb-10">
          <div className="h-px bg-foreground/20 mb-4" />
          <div className="flex items-center justify-between">
            <button onClick={() => navigate('/')} className="text-xs font-newspaper text-foreground/60 hover:text-foreground hover:underline transition-colors">
              &larr; 返回
            </button>
            <span className="text-xs font-newspaper text-foreground/40 tracking-widest uppercase">Agent 世界</span>
          </div>
          <div className="text-center mt-4 mb-2">
            <h1 className="text-3xl md:text-4xl font-newspaper-bold text-foreground tracking-tight">Agent 库</h1>
            <p className="font-newspaper text-foreground/40 text-sm mt-1">浏览和管理你的 AI Agent，点击卡片查看详情</p>
          </div>
          <div className="flex items-center justify-center gap-4 mt-4 mb-2">
            <button onClick={() => setExportOpen(true)} className="text-xs font-newspaper text-foreground/60 hover:text-foreground hover:underline transition-colors flex items-center gap-1">
              <DownloadIcon className="w-3.5 h-3.5" /> 导出
            </button>
            <span className="text-foreground/20">|</span>
            <button onClick={() => setImportOpen(true)} className="text-xs font-newspaper text-foreground/60 hover:text-foreground hover:underline transition-colors flex items-center gap-1">
              <UploadIcon className="w-3.5 h-3.5" /> 导入
            </button>
            <span className="text-foreground/20">|</span>
            <button onClick={() => setEditing({ kind: 'create', nonce: Date.now() })} className="text-xs font-newspaper-bold text-foreground/80 hover:text-foreground hover:underline transition-colors flex items-center gap-1">
              <PlusIcon className="w-3.5 h-3.5" /> 创建 Agent
            </button>
          </div>
          <div className="h-px bg-foreground/20 mt-4" />
        </div>

        {/* Search */}
        <div className="mb-8">
          <div className="relative max-w-md">
            <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground/40" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索 Agent..."
              className="w-full pl-10 pr-4 py-2.5 border border-foreground/15 text-sm font-newspaper text-foreground placeholder:text-foreground/40 focus:outline-none focus:border-foreground/30" />
          </div>
        </div>

        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {Array.from({ length: 8 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        )}

        {!isLoading && agents.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-16 h-16 border border-foreground/15 flex items-center justify-center bg-foreground/5">
              <BotIcon className="w-8 h-8 text-foreground/30" />
            </div>
            <div className="text-center">
              <p className="text-base font-newspaper-bold text-foreground mb-1">还没有 Agent</p>
              <p className="text-sm font-newspaper text-foreground/40">点击「创建 Agent」开始添加你的第一个 AI 角色</p>
            </div>
            <button onClick={() => setEditing({ kind: 'create', nonce: Date.now() })} className="text-sm font-newspaper-bold text-foreground/80 hover:text-foreground hover:underline transition-colors flex items-center gap-1">
              <PlusIcon className="w-4 h-4" />创建 Agent
            </button>
          </div>
        )}

        {!isLoading && filtered.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filtered.map((agent: any) => {
              return (
                <div
                  key={agent.id}
                  onClick={() => setSelectedAgent(agent)}
                  className="border border-foreground/15 p-5 transition-all duration-200 cursor-pointer group hover:border-foreground/25"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 border border-foreground/15 flex items-center justify-center text-2xl bg-foreground/5">
                        {agent.avatar || '🤖'}
                      </div>
                      <div>
                        <h3 className="text-sm font-newspaper-bold text-foreground group-hover:underline transition-all">{agent.name}</h3>
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={(e) => { e.stopPropagation(); setEditing({ kind: 'edit', agent }); }} className="p-1.5 hover:bg-foreground/5 transition-colors" title="编辑">
                        <EditIcon className="w-3.5 h-3.5 text-foreground/40" />
                      </button>
                      <button onClick={(e) => handleDelete(e, agent.id)} className="p-1.5 hover:bg-foreground/5 transition-colors" title="删除">
                        <TrashIcon className="w-3.5 h-3.5 text-foreground/40 hover:text-foreground/80" />
                      </button>
                    </div>
                  </div>
                  <p className="text-xs font-newspaper text-foreground/40 leading-relaxed line-clamp-2 mb-3">{agent.description || '暂无描述'}</p>
                  {agent.capabilities?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {agent.capabilities.slice(0, 3).map((cap: string) => (
                        <span key={cap} className="text-xs font-newspaper text-foreground/60">{cap}</span>
                      ))}
                      {agent.capabilities.length > 3 && <span className="text-xs text-foreground/40">+{agent.capabilities.length - 3}</span>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {editing && (
        <AgentEditor
          key={editing.kind === 'create' ? `new-${editing.nonce}` : `edit-${editing.agent.id}`}
          initial={editing.kind === 'create' ? null : editing.agent}
          onClose={() => setEditing(null)}
          onSave={handleSave}
          isPending={editing.kind === 'create' ? createMutation.isPending : updateMutation.isPending}
        />
      )}

      {displayAgent && (
        <AgentCard
          agent={displayAgent}
          onClose={() => setSelectedAgent(null)}
          onEdit={() => { setEditing({ kind: 'edit', agent: displayAgent }); setSelectedAgent(null); }}
        />
      )}

      {/* 导出对话框 */}
      <ExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        type="agent"
        title="导出 Agent"
        items={exportableAgents || []}
        loading={exportLoading}
        exporting={exportDownload.isPending}
        onExport={(items: ExportRequestItem[]) => {
          exportDownload.mutate({ items, filename: 'agents_export.zip' }, {
            onSuccess: () => setExportOpen(false),
          })
        }}
      />

      {/* 导入对话框 */}
      <ImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        type="agent"
        previewResult={importPreview.data?.data ?? null}
        previewing={importPreview.isPending}
        executeResult={importExecute.data?.data ?? null}
        executing={importExecute.isPending}
        onPreview={(file: File) => importPreview.mutate(file)}
        onExecute={(file: File, resolutions: ConflictResolution[]) => {
          importExecute.mutate({ file, resolutions }, {
            onSuccess: () => {
              importPreview.reset()
              refetch()
            },
          })
        }}
      />
    </div>
  );
}
