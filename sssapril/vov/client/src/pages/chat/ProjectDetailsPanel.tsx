import {
  ArrowLeftIcon, DownloadIcon, RefreshCwIcon, LayoutDashboardIcon,
} from 'lucide-react';
import { useChatPage, groupStatusConfig, exportModes, labelForCount } from './context';
import ProjectContentTree from '../../components/project/ProjectContentTree';
import { paperCoverColor } from '../../lib/coverColor';

export default function ProjectDetailsPanel() {
  const {
    mainMode, setMainMode,
    project, projectId, navigate,
    sortedGroups, projectAgentsData, projectResources,
    previewBundle, exportBundle, projectBundleSelection,
    projectTreeNodes, projectTreeExpanded, setProjectTreeExpanded,
    projectTreeSelection, setProjectTreeSelection,
    exportMode,
    handleProjectExport, handleProjectExportMode,
  } = useChatPage();

  const isExport = mainMode === 'project-export';
  const preview = previewBundle.data?.data;
  const coverClass = paperCoverColor(project.cover_color, project.id);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 px-6 py-2.5 border-b border-foreground/15 flex-shrink-0 h-12">
        <button
          onClick={() => setMainMode('chat')}
          className="flex items-center gap-1.5 text-sm text-foreground/40 hover:text-foreground/80 transition-colors group font-newspaper"
        >
          <ArrowLeftIcon className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
          <span>返回项目对话</span>
        </button>
        <span className="text-foreground/40 text-sm font-newspaper">/</span>
        <div className="flex items-center gap-1.5">
          <div className={`w-4 h-4 bg-gradient-to-br ${coverClass} flex-shrink-0`} />
          <span className="text-sm font-newspaper-bold text-foreground/80">{project.name}</span>
        </div>
        <span className="text-foreground/40 text-sm font-newspaper">/</span>
        <span className="text-sm text-foreground/40 font-newspaper">项目详情</span>
        <div className="ml-auto flex items-center gap-2">
          {isExport ? (
            <button onClick={() => setMainMode('project-details')} className="border border-foreground/20 px-3 py-1.5 text-sm font-newspaper text-foreground/60 hover:bg-foreground/5 transition-colors">退出导出</button>
          ) : (
            <button onClick={() => setMainMode('project-export')} className="flex items-center gap-1.5 border border-foreground/30 px-3 py-1.5 text-sm font-newspaper-bold text-foreground/80 hover:bg-foreground/5 transition-all duration-200">
              <DownloadIcon className="h-4 w-4" />
              导出
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-72 flex-shrink-0 border-r border-foreground/15 flex flex-col overflow-hidden">
          <div className="px-3 py-3 border-b border-foreground/15 flex-shrink-0">
            <div className="flex items-center gap-2">
              <LayoutDashboardIcon className="w-4 h-4 text-foreground/60" />
              <h2 className="text-xs font-newspaper-bold text-foreground/80">{isExport ? '选择导出内容' : '项目结构'}</h2>
            </div>
            <p className="mt-0.5 text-[10px] text-foreground/30 font-newspaper">{isExport ? '勾选需要导出的内容' : '浏览项目资产树'}</p>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            <ProjectContentTree
              nodes={projectTreeNodes}
              mode={isExport ? 'select' : 'view'}
              selection={projectTreeSelection}
              expanded={projectTreeExpanded}
              onExpandedChange={setProjectTreeExpanded}
              onSelectionChange={setProjectTreeSelection}
            />
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!isExport ? (
              <div className="mx-auto max-w-3xl flex flex-col gap-4">
                <div className="border border-foreground/15 p-3">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={`w-8 h-8 bg-gradient-to-br ${coverClass} flex items-center justify-center`}>
                      <span className="text-sm font-newspaper-bold text-foreground/80">{project.name?.charAt(0)}</span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-newspaper-bold text-foreground/80 truncate">{project.name}</h3>
                      <p className="text-xs text-foreground/30 truncate font-newspaper">{project.description || '暂无描述'}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(preview?.counts || { agents: projectAgentsData?.items?.length || 0, groups: sortedGroups.length, tasks: 0, resources: projectResources.length }).slice(0, 8).map(([key, value]) => (
                      <div key={key} className="border border-foreground/15 p-2 flex items-center justify-between">
                        <span className="text-[11px] text-foreground/30 font-newspaper">{labelForCount(key)}</span>
                        <span className="text-sm font-newspaper-bold text-foreground/80 tabular-nums">{value as React.ReactNode}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="border border-foreground/15 p-3">
                  <h4 className="text-xs font-newspaper-bold text-foreground/80 mb-2">群聊列表</h4>
                  <div className="flex flex-col gap-1">
                    {sortedGroups.map(g => {
                      const cfg = groupStatusConfig[g.status];
                      return (
                        <div key={g.id} className="flex items-center gap-2 px-2 py-1.5 border border-foreground/15 hover:border-foreground/30 transition-colors">
                          <div className="w-1.5 h-1.5 bg-foreground/60" />
                          <div className="flex-1 min-w-0">
                            <span className="text-xs font-newspaper-bold text-foreground/80 truncate">{g.name}</span>
                          </div>
                          <span className="text-[10px] text-foreground/30 flex-shrink-0 font-newspaper">{cfg.label} · {g.task_count}任务</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl flex flex-col gap-4">
                <div>
                  <div className="mb-2 text-[10px] font-newspaper-bold uppercase tracking-widest text-foreground/30">导出预设</div>
                  <div className="grid grid-cols-2 gap-2">
                    {exportModes.map(mode => (
                      <button
                        key={mode.value}
                        onClick={() => handleProjectExportMode(mode.value)}
                        className={`border px-3 py-2 text-xs font-newspaper transition-all duration-200 ${
                          exportMode === mode.value
                            ? 'border-foreground/30 bg-foreground/5 text-foreground/80'
                            : 'border-foreground/15 text-foreground/40 hover:bg-foreground/5'
                        }`}
                      >
                        {mode.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div className="text-xs font-newspaper-bold text-foreground/80">导出预览</div>
                  <button onClick={() => projectId && previewBundle.mutate({ projectId, selection: projectBundleSelection })} className="p-1 hover:bg-foreground/5 transition-colors">
                    <RefreshCwIcon className={`h-3.5 w-3.5 text-foreground/40 ${previewBundle.isPending ? 'animate-spin' : ''}`} />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(preview?.counts || {}).map(([key, value]) => (
                    <div key={key} className="border border-foreground/15 p-2 flex items-center justify-between">
                      <span className="text-[11px] text-foreground/30 font-newspaper">{labelForCount(key)}</span>
                      <span className="text-sm font-newspaper-bold text-foreground/80 tabular-nums">{value as React.ReactNode}</span>
                    </div>
                  ))}
                </div>

                {preview?.warnings?.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    {preview.warnings.map((warning: string) => (
                      <div key={warning} className="border border-foreground/20 px-2.5 py-1.5 text-xs text-foreground/60 font-newspaper">
                        {warning}
                      </div>
                    ))}
                  </div>
                )}

                <button onClick={handleProjectExport} disabled={exportBundle.isPending} className="mt-auto flex w-full items-center justify-center gap-2 border border-foreground/30 px-3 py-2 text-xs font-newspaper-bold text-foreground/80 hover:bg-foreground/5 transition-all duration-200 disabled:opacity-60 disabled:shadow-none">
                  <DownloadIcon className="h-3.5 w-3.5" />
                  {exportBundle.isPending ? '导出中...' : '导出 ZIP'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
