import {
  ArrowLeftIcon, BotIcon, FileTextIcon, SettingsIcon, FolderTreeIcon,
} from 'lucide-react';
import { useChatPage, groupStatusConfig } from './context';
import { paperCoverColor } from '../../lib/coverColor';

export default function ChatTopBar() {
  const {
    navigate, project, group, activeReplyChain,
    setEditingGroup, setMainMode,
  } = useChatPage();

  const doneTasks = (group.tasks || []).filter((t: any) => t.status === 'done').length;
  const coverClass = paperCoverColor(project.cover_color, project.id);

  return (
    <header className="flex items-center gap-3 px-6 py-2.5 border-b border-foreground/15 flex-shrink-0 h-12">
      <button
        onClick={() => navigate('/')}
        className="flex items-center gap-1.5 text-sm text-foreground/40 hover:text-foreground/80 transition-colors group font-newspaper"
      >
        <ArrowLeftIcon className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
        <span>项目列表</span>
      </button>
      <span className="text-foreground/40 text-sm font-newspaper">/</span>
      <div className="flex items-center gap-1.5">
        <div className={`w-4 h-4 bg-gradient-to-br ${coverClass} flex-shrink-0`} />
        <span className="text-sm text-foreground/60 truncate max-w-40 font-newspaper">{project.name}</span>
        <button
          onClick={() => setMainMode('project-details')}
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-newspaper-bold transition-all duration-200 border-b border-foreground/60"
        >
          <FolderTreeIcon className="w-3 h-3" />
          详情
        </button>
      </div>
      <span className="text-foreground/40 text-sm font-newspaper">/</span>
      <span className="text-sm font-newspaper-bold text-foreground/80 truncate max-w-48">{group.name}</span>

      {/* Chain 导航面包屑 */}
      {activeReplyChain && activeReplyChain.chain.chain_type === 'task' && (
        <>
          <span className="text-foreground/40 text-sm font-newspaper">/</span>
          <span className="text-sm font-newspaper-bold text-foreground/60 truncate max-w-48">
            {activeReplyChain.chain.description || '任务进行中'}
          </span>
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-foreground/40 px-2.5 py-1 font-newspaper">
          <BotIcon className="w-3.5 h-3.5" />
          {(group.members || []).length} Agents
        </div>
        <div className="flex items-center gap-1.5 text-xs text-foreground/40 px-2.5 py-1 font-newspaper">
          <FileTextIcon className="w-3.5 h-3.5" />
          {doneTasks}/{(group.tasks || []).length} 任务
        </div>
        <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1 font-newspaper ${groupStatusConfig[group.status].color}`}>
          <div className="w-1.5 h-1.5 bg-foreground/60" />
          {groupStatusConfig[group.status].label}
        </div>
        <button
          onClick={() => setEditingGroup(true)}
          className="p-1.5 hover:bg-foreground/5 transition-colors"
          title="群聊设置"
        >
          <SettingsIcon className="w-4 h-4 text-foreground/40" />
        </button>
      </div>
    </header>
  );
}
