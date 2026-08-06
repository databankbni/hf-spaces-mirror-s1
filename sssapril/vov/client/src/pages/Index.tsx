import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { PlusIcon, BotIcon, FolderIcon, LayersIcon, SettingsIcon, ZapIcon, MoreVerticalIcon, EditIcon, TrashIcon, DownloadIcon } from 'lucide-react';
import { useProjects, useDeleteProject } from '../hooks/useProjects';
import { projectBundleApi } from '../api/projectBundles';
import { toast } from 'sonner';
import { useAppStore } from '../store/appStore';
import CreateProjectModal from '../components/CreateProjectModal';
import ConfirmDialog from '../components/ConfirmDialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../components/ui/dropdown-menu';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { useTheme } from '../hooks/useTheme';
import TypewriterText from '../components/TypewriterText';
import type { ProjectListItem } from '../types';

export default function Index() {
  const { data: projectsData, isLoading, error } = useProjects();
  const navigate = useNavigate();
  const [showCreate, setShowCreate] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectListItem | null>(null);
  const [deletingProject, setDeletingProject] = useState<ProjectListItem | null>(null);
  const setActiveProjectId = useAppStore((state) => state.setActiveProjectId);
  const setUniversalChatOpen = useAppStore((state) => state.setUniversalChatOpen);
  const deleteProjectMutation = useDeleteProject();
  const { derived, config } = useTheme();

  const handleOpenProject = async (projectId: string) => {
    setActiveProjectId(projectId);
    // L1: 跳到项目概览页（显示群聊列表 + 召唤入口），不再直接进群聊
    navigate(`/project/${projectId}`);
  };

  const handleDeleteProject = async () => {
    if (!deletingProject) return;
    await deleteProjectMutation.mutateAsync(deletingProject.id);
  };

  const handleExportProject = async (project: ProjectListItem) => {
    try {
      await projectBundleApi.download(project.id, {
        mode: 'backup', project_meta: true, agents: true, skills: true,
        groups: true, tasks: true, resources: { include: true, types: [], ids: [], required_only: false },
        deliverables: true, messages: true, memories: true, tags: true,
      }, `${project.name}_备份.zip`);
      toast.success('导出成功');
    } catch { toast.error('导出失败'); }
  };

  // T12: 过滤掉引导 project，不展示在"我的项目"列表
  const projectList = (projectsData?.items || []).filter(p => !p.is_guide);
  const totalAgents = projectList.reduce((s, p) => s + (p.agent_count || 0), 0);
  const activeProjects = projectList.filter(p => p.status === 'active').length;
  // T11: 首次无项目时自动展开引导侧边栏（防重复）
  const autoOpenedRef = useRef(false);
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (!isLoading && projectList.length === 0) {
      autoOpenedRef.current = true;
      setUniversalChatOpen(true);
    }
  }, [isLoading, projectList.length, setUniversalChatOpen]);
  const isLetter = config.style === 'letter';
  const letterhead = derived.chrome.letterhead;

  // 加载态
  if (isLoading) {
    return (
      <div className="newspaper-bg min-h-screen">
        <div className="max-w-[1100px] mx-auto px-8 md:px-12 py-8">
          <Skeleton className="h-20 w-full mb-4" style={{ background: '#d5c4a1' }} />
          <Skeleton className="h-40 w-full mb-4" style={{ background: '#d5c4a1' }} />
          <div className="grid grid-cols-3 gap-4">
            <Skeleton className="h-48" style={{ background: '#d5c4a1' }} />
            <Skeleton className="h-48" style={{ background: '#d5c4a1' }} />
            <Skeleton className="h-48" style={{ background: '#d5c4a1' }} />
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="newspaper-bg min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">⚠️</div>
          <p className="text-lg font-semibold mb-2">加载失败</p>
          <p className="text-sm opacity-60 mb-6">{error.message}</p>
          <Button onClick={() => window.location.reload()}>重试</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="newspaper-bg min-h-screen">
      <div className="max-w-[1100px] mx-auto border-x border-foreground/10">
        <div className="px-8 md:px-12 py-8 md:py-10 pb-16 md:pb-20">

        {/* ═══ 信笺头（仅 letter 风格显示） ═══ */}
        {isLetter && letterhead && (
          <header className="mb-6">
            <div className="text-right text-xs opacity-50 mb-3 font-newspaper tracking-wider">
              {new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}
            </div>
            <div className="text-2xl md:text-3xl font-newspaper-bold mb-4" style={{ fontFamily: '"Ma Shan Zheng", "KaiTi", "楷体", serif' }}>
              <TypewriterText text={letterhead.greeting} speed={80} enabled={derived.pacing === 'typewriter'} />
            </div>
            <div className="h-px bg-foreground/30 mb-4" />
          </header>
        )}

        {/* ═══ 报头（默认/柔和/手抄报 显示；letter 隐藏） ═══ */}
        {derived.chrome.showLogo && (
          <header className="text-center mb-2">
            <div className="flex items-center justify-center gap-3 mb-1">
              <div className="h-px flex-1 bg-foreground/30" />
              <ZapIcon className="w-5 h-5 text-foreground/70" />
              <h1 className="text-3xl md:text-4xl font-newspaper tracking-wider">vov</h1>
              <ZapIcon className="w-5 h-5 text-foreground/70" />
              <div className="h-px flex-1 bg-foreground/30" />
            </div>
            {derived.chrome.showSubtitle && (
              <p className="text-xs tracking-[0.3em] uppercase opacity-50 font-newspaper">多 Agent 创作平台</p>
            )}
          </header>
        )}

        {/* 双线分割（仅在 chrome.showDividers 时） */}
        {derived.chrome.showDividers && (
          <div className="my-4">
            <div className="h-[2px] bg-foreground/80" />
            <div className="h-px bg-foreground/30 mt-[3px]" />
          </div>
        )}

        {/* ═══ 导航 ═══ */}
        {derived.chrome.showNav && (
          <nav className="flex items-center justify-between text-xs mb-1">
            <div className="flex items-center gap-4 px-1">
              <span className="font-newspaper-bold text-foreground/80">项目</span>
              <span className="opacity-40">|</span>
              <button onClick={() => navigate('/agents')} className="opacity-60 hover:opacity-100 transition-opacity">Agent</button>
              <button onClick={() => navigate('/skills')} className="opacity-60 hover:opacity-100 transition-opacity">技能</button>
              <button onClick={() => navigate('/tools')} className="opacity-60 hover:opacity-100 transition-opacity">工具</button>
            </div>
            <div className="flex items-center gap-3 px-1">
              <button onClick={() => navigate('/settings')} className="opacity-40 hover:opacity-80 transition-opacity">设置</button>
              <button onClick={() => setShowCreate(true)} className="font-newspaper-bold text-foreground hover:opacity-70 transition-opacity">+ 新建</button>
            </div>
          </nav>
        )}

        {/* 单线分割（仅在 chrome.showDividers 时） */}
        {derived.chrome.showDividers && <div className="h-px bg-foreground/20 my-2" />}

        {/* ═══ 日期行 ═══ */}
        {derived.chrome.showDateRow && (
          <div className="flex items-center justify-between text-[10px] opacity-40 mb-6 px-1">
            <span>{new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}</span>
            <span>{activeProjects} 个进行中 · {totalAgents} 个Agent就绪</span>
          </div>
        )}

        {/* ═══ 主内容区 ═══ */}
        {projectList.length === 0 ? (
          <div className="text-center py-20">
            <FolderIcon className="w-10 h-10 mx-auto mb-4 opacity-30" />
            <p className="font-newspaper text-lg mb-1">尚无项目</p>
            <p className="text-xs opacity-50 mb-4">
              不知道从哪开始？按 <kbd className="rounded bg-foreground/10 px-1.5 py-0.5">⌘K</kbd> 召唤引导助手，告诉它你想做什么
            </p>
            <button onClick={() => setUniversalChatOpen(true)} className="text-xs font-newspaper-bold opacity-70 hover:opacity-100 transition-opacity underline">
              召唤引导助手
            </button>
          </div>
        ) : (
          <>
            {/* 第一个项目：大版面 */}
            {projectList[0] && (
              <NewspaperLargeCard
                project={projectList[0]}
                onOpen={handleOpenProject}
                onEdit={setEditingProject}
                onDelete={setDeletingProject}
                onExport={handleExportProject}
              />
            )}

            {/* 分割线 */}
            {projectList.length > 1 && derived.chrome.showDividers && (
              <div className="my-4">
                <div className="h-px bg-foreground/20" />
                <div className="flex items-center justify-center -mt-2">
                  <span className="bg-paper px-3 text-[10px] opacity-40">· · ·</span>
                </div>
              </div>
            )}

            {/* 中间项目：两列 */}
            {projectList.length > 1 && (
              <div className={`grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 ${derived.layout === 'scattered' ? 'scattered-grid' : ''}`}>
                {projectList.slice(1, 3).map((project, idx) => (
                  <NewspaperMediumCard
                    key={project.id}
                    project={project}
                    onOpen={handleOpenProject}
                    onEdit={setEditingProject}
                    onDelete={setDeletingProject}
                    onExport={handleExportProject}
                    rotation={derived.layout === 'scattered' ? (idx % 2 === 0 ? -0.4 : 0.5) : 0}
                  />
                ))}
              </div>
            )}

            {/* 分割线 */}
            {projectList.length > 3 && derived.chrome.showDividers && (
              <div className="my-4">
                <div className="h-px bg-foreground/20" />
              </div>
            )}

            {/* 更多项目：三列 / 紧凑 / 错落 */}
            {projectList.length > 3 && (
              <div className={
                derived.layout === 'compact'
                  ? 'flex flex-col gap-2'
                  : derived.layout === 'scattered'
                    ? 'scattered-grid grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-5'
                    : 'grid grid-cols-1 md:grid-cols-3 gap-x-5 gap-y-3'
              }>
                {projectList.slice(3).map((project, idx) => (
                  <NewspaperSmallCard
                    key={project.id}
                    project={project}
                    onOpen={handleOpenProject}
                    onEdit={setEditingProject}
                    onDelete={setDeletingProject}
                    onExport={handleExportProject}
                    rotation={derived.layout === 'scattered' ? (idx % 3 === 0 ? -0.6 : idx % 3 === 1 ? 0.4 : -0.3) : 0}
                  />
                ))}
              </div>
            )}

            {/* ═══ 底部新建 ═══ */}
            <div className="mt-4">
              <button
                onClick={() => setShowCreate(true)}
                className="w-full border border-dashed border-foreground/20 py-6 text-center opacity-40 hover:opacity-80 hover:border-foreground/40 transition-all text-xs font-newspaper tracking-wider"
              >
                + 创建新项目
              </button>
            </div>
          </>
        )}

        {/* ═══ 报尾（letter 风格改为信笺落款） ═══ */}
        {derived.chrome.showFooter ? (
          <div className="mt-8">
            <div className="h-[2px] bg-foreground/80" />
            <div className="h-px bg-foreground/30 mt-[3px]" />
            <div className="flex items-center justify-between text-[10px] opacity-30 mt-2 font-newspaper px-1">
              <span>vov · 多Agent创作平台</span>
              <span>{projectList.length} 个项目 · {totalAgents} 个Agent</span>
            </div>
          </div>
        ) : isLetter && letterhead ? (
          <div className="mt-12 text-right">
            <div className="inline-block">
              <div className="text-base md:text-lg" style={{ fontFamily: '"Ma Shan Zheng", "KaiTi", "楷体", serif' }}>
                {letterhead.signature}
              </div>
              <div className="mt-2 h-px bg-foreground/30 w-32 ml-auto" />
            </div>
          </div>
        ) : null}
        </div>
      </div>

      {/* ═══ 弹窗 ═══ */}
      <CreateProjectModal
        open={showCreate || !!editingProject}
        onClose={() => { setShowCreate(false); setEditingProject(null); }}
        onCreated={async (id) => { setActiveProjectId(id); await handleOpenProject(id); }}
        onUpdated={() => setEditingProject(null)}
        project={editingProject || undefined}
      />

      <ConfirmDialog
        open={!!deletingProject}
        onClose={() => setDeletingProject(null)}
        onConfirm={handleDeleteProject}
        title="删除项目"
        description={`确定要删除项目「${deletingProject?.name}」吗？此操作不可撤销。`}
        confirmText="删除"
        destructive
      />
    </div>
  );
}

// ── 大版面卡片 ──

function NewspaperLargeCard({ project, onOpen, onEdit, onDelete, onExport }: {
  project: ProjectListItem; onOpen: (id: string) => void; onEdit: (p: ProjectListItem) => void;
  onDelete: (p: ProjectListItem) => void; onExport: (p: ProjectListItem) => void;
}) {
  const progress = project.task_count > 0 ? Math.round((project.done_task_count / project.task_count) * 100) : 0;

  return (
    <div className="group relative">
      {/* 操作菜单 */}
      <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button onClick={e => e.stopPropagation()} className="p-1 bg-foreground/10 rounded hover:bg-foreground/20 transition-colors">
              <MoreVerticalIcon className="w-3.5 h-3.5 text-foreground/70" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onExport(project)}><DownloadIcon className="w-3.5 h-3.5 mr-2" />导出</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onEdit(project)}><EditIcon className="w-3.5 h-3.5 mr-2" />编辑</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => onDelete(project)}><TrashIcon className="w-3.5 h-3.5 mr-2" />删除</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <button onClick={() => onOpen(project.id)} className="w-full text-left">
        {/* 两列：封面 + 文字 */}
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1.2fr] gap-0 border border-foreground/15">
          {/* 封面 */}
          <div className="h-40 md:h-auto bg-foreground/5 border-b md:border-b-0 md:border-r border-foreground/15 flex items-center justify-center relative overflow-hidden">
            <div className="absolute inset-0 newspaper-dots opacity-30" />
            <div className="text-center relative z-10">
              <FolderIcon className="w-8 h-8 mx-auto mb-2 text-foreground/20" />
              <span className="text-[10px] font-newspaper tracking-widest uppercase opacity-30">项目</span>
            </div>
          </div>

          {/* 文字区 */}
          <div className="p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                {project.status === 'active' && <span className="w-1.5 h-1.5 rounded-full bg-foreground/60 animate-pulse" />}
                <h2 className="text-xl md:text-2xl font-newspaper-bold leading-tight">{project.name}</h2>
              </div>
              {project.description && (
                <p className="text-xs opacity-50 leading-relaxed line-clamp-2 mb-3">{project.description}</p>
              )}
            </div>

            <div className="space-y-2">
              {project.task_count > 0 && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-[3px] bg-foreground/10 rounded-full overflow-hidden">
                    <div className="h-full bg-foreground/50 rounded-full" style={{ width: `${progress}%` }} />
                  </div>
                  <span className="text-[10px] opacity-50 tabular-nums">{project.done_task_count || 0}/{project.task_count}</span>
                </div>
              )}
              <div className="flex items-center gap-3 text-[10px] opacity-40">
                <span className="flex items-center gap-1"><LayersIcon className="w-3 h-3" />{project.group_count || 0} 群聊</span>
                <span className="flex items-center gap-1"><BotIcon className="w-3 h-3" />{project.agent_count || 0} Agent</span>
                <span>{new Date(project.updated_at).toLocaleDateString()}</span>
              </div>
            </div>
          </div>
        </div>
      </button>
    </div>
  );
}

// ── 中版面卡片 ──

function NewspaperMediumCard({ project, onOpen, onEdit, onDelete, onExport, rotation = 0 }: {
  project: ProjectListItem; onOpen: (id: string) => void; onEdit: (p: ProjectListItem) => void;
  onDelete: (p: ProjectListItem) => void; onExport: (p: ProjectListItem) => void;
  rotation?: number;
}) {
  const progress = project.task_count > 0 ? Math.round((project.done_task_count / project.task_count) * 100) : 0;

  return (
    <div
      className="group relative border border-foreground/15 p-5"
      style={rotation ? { transform: `rotate(${rotation}deg)`, transformOrigin: 'center' } : undefined}
    >
      <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button onClick={e => e.stopPropagation()} className="p-1 bg-foreground/10 rounded hover:bg-foreground/20 transition-colors">
              <MoreVerticalIcon className="w-3.5 h-3.5 text-foreground/70" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onExport(project)}><DownloadIcon className="w-3.5 h-3.5 mr-2" />导出</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onEdit(project)}><EditIcon className="w-3.5 h-3.5 mr-2" />编辑</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => onDelete(project)}><TrashIcon className="w-3.5 h-3.5 mr-2" />删除</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <button onClick={() => onOpen(project.id)} className="w-full text-left">
        <h3 className="text-base font-newspaper-bold leading-tight mb-1 pr-6">{project.name}</h3>
        {project.description && (
          <p className="text-[11px] opacity-45 leading-relaxed line-clamp-2 mb-3">{project.description}</p>
        )}
        <div className="h-px bg-foreground/10 my-2" />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-[10px] opacity-40">
            <span className="flex items-center gap-1"><LayersIcon className="w-3 h-3" />{project.group_count || 0}</span>
            <span className="flex items-center gap-1"><BotIcon className="w-3 h-3" />{project.agent_count || 0}</span>
          </div>
          {project.task_count > 0 && (
            <div className="flex items-center gap-1.5">
              <div className="w-16 h-[3px] bg-foreground/10 rounded-full overflow-hidden">
                <div className="h-full bg-foreground/40 rounded-full" style={{ width: `${progress}%` }} />
              </div>
              <span className="text-[10px] opacity-50 tabular-nums">{project.done_task_count || 0}/{project.task_count}</span>
            </div>
          )}
        </div>
      </button>
    </div>
  );
}

// ── 小版面卡片 ──

function NewspaperSmallCard({ project, onOpen, onEdit, onDelete, onExport, rotation = 0 }: {
  project: ProjectListItem; onOpen: (id: string) => void; onEdit: (p: ProjectListItem) => void;
  onDelete: (p: ProjectListItem) => void; onExport: (p: ProjectListItem) => void;
  rotation?: number;
}) {
  return (
    <div
      className="group relative border border-foreground/15 p-4"
      style={rotation ? { transform: `rotate(${rotation}deg)`, transformOrigin: 'center' } : undefined}
    >
      <div className="absolute top-1.5 right-1.5 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button onClick={e => e.stopPropagation()} className="p-0.5 bg-foreground/10 rounded hover:bg-foreground/20 transition-colors">
              <MoreVerticalIcon className="w-3 h-3 text-foreground/70" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onExport(project)}><DownloadIcon className="w-3 h-3 mr-2" />导出</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onEdit(project)}><EditIcon className="w-3 h-3 mr-2" />编辑</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => onDelete(project)}><TrashIcon className="w-3 h-3 mr-2" />删除</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <button onClick={() => onOpen(project.id)} className="w-full text-left">
        <h4 className="text-sm font-newspaper-bold leading-tight mb-1 pr-5">{project.name}</h4>
        {project.description && (
          <p className="text-[10px] opacity-40 line-clamp-2 mb-2">{project.description}</p>
        )}
        <div className="flex items-center gap-2 text-[9px] opacity-35">
          <span>{project.group_count || 0} 群聊</span>
          <span>·</span>
          <span>{project.agent_count || 0} Agent</span>
          {project.task_count > 0 && (
            <>
              <span>·</span>
              <span>{project.done_task_count || 0}/{project.task_count}</span>
            </>
          )}
        </div>
      </button>
    </div>
  );
}
