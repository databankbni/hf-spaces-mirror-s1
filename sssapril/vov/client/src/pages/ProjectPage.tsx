import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeftIcon, MessageSquareIcon, SparklesIcon, UsersIcon } from 'lucide-react';
import { useGroups } from '../hooks/useGroups';
import { useProject } from '../hooks/useProjects';
import { useAppStore, CHAT_HOTKEY_OPTIONS, type ChatHotkey } from '../store/appStore';

/**
 * 项目概览页（L1 场景入口）
 *
 * 不再直接重定向到第一个群聊，而是显示：
 * - 项目名称 + 描述
 * - 群聊列表（点击进入群聊）
 * - 无群聊时显示空状态 + 召唤提示（Cmd+K 调出项目总控 coordinator）
 *
 * UniversalChat 全局挂载，在 /project/:id 路由下自动切换为 L1 模式（coordinator）。
 */
export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading: projectLoading } = useProject(projectId || '');
  const { data: groupsData, isLoading: groupsLoading } = useGroups(projectId || '');
  const setUniversalChatOpen = useAppStore((s) => s.setUniversalChatOpen);
  const chatHotkey = useAppStore((s) => s.chatHotkey);
  const hotkeyLabel = CHAT_HOTKEY_OPTIONS.find(o => o.key === chatHotkey)?.label ?? `⌘${chatHotkey.toUpperCase()}`;

  const groups = groupsData?.items || [];
  const isLoading = projectLoading || groupsLoading;

  return (
    <div className="min-h-screen newspaper-bg">
      <div className="max-w-[1100px] mx-auto px-8 md:px-12 py-8">
        {/* 顶部导航 */}
        <button
          onClick={() => navigate('/')}
          className="mb-6 inline-flex items-center gap-1.5 text-sm text-foreground/60 hover:text-foreground transition-colors font-newspaper"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          返回首页
        </button>

        {/* 项目标题 */}
        <header className="mb-8 border-b border-foreground/15 pb-6">
          <h1 className="font-newspaper-bold text-4xl text-foreground mb-2">
            {isLoading ? '加载中…' : project?.name || '未知项目'}
          </h1>
          <p className="text-sm text-foreground/60 font-newspaper">
            {project?.description || '暂无描述'}
          </p>
        </header>

        {/* 群聊列表区 */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-newspaper-bold text-xl text-foreground flex items-center gap-2">
              <MessageSquareIcon className="h-5 w-5" />
              群聊
              {groups.length > 0 && (
                <span className="text-sm font-normal text-foreground/40">({groups.length})</span>
              )}
            </h2>
            <button
              onClick={() => setUniversalChatOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-foreground/20 px-3 py-1.5 text-sm text-foreground/70 hover:border-foreground/40 hover:text-foreground transition-colors font-newspaper"
            >
              <SparklesIcon className="h-3.5 w-3.5" />
              召唤项目总控
              <kbd className="ml-1 rounded border border-foreground/15 bg-foreground/5 px-1 py-0.5 text-[10px]">{hotkeyLabel}</kbd>
            </button>
          </div>

          {/* 加载中 */}
          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-32 rounded-lg border border-foreground/10 bg-foreground/5 animate-pulse" />
              ))}
            </div>
          ) : groups.length === 0 ? (
            /* 空状态：无群聊，引导用户召唤 coordinator */
            <div className="rounded-lg border border-dashed border-foreground/20 bg-background/50 p-12 text-center">
              <div className="mb-4 text-4xl">🧭</div>
              <h3 className="font-newspaper-bold text-lg text-foreground mb-2">项目还没有群聊</h3>
              <p className="text-sm text-foreground/60 mb-6 max-w-md mx-auto">
                按下 <kbd className="rounded border border-foreground/20 bg-foreground/5 px-1.5 py-0.5 text-xs">{hotkeyLabel}</kbd> 召唤项目总控，
                告诉它你想怎么开工，它会帮你建群聊、分方向、规划流程。
              </p>
              <button
                onClick={() => setUniversalChatOpen(true)}
                className="inline-flex items-center gap-2 rounded-md bg-foreground px-4 py-2 text-sm text-background hover:opacity-90 transition-opacity font-newspaper"
              >
                <SparklesIcon className="h-4 w-4" />
                召唤项目总控
              </button>
            </div>
          ) : (
            /* 群聊卡片列表 */
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {groups.map((group) => (
                <button
                  key={group.id}
                  onClick={() => navigate(`/project/${projectId}/chat/${group.id}`)}
                  className="group rounded-lg border border-foreground/15 bg-background p-5 text-left transition-all hover:border-foreground/30 hover:shadow-md"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-newspaper-bold text-base text-foreground truncate group-hover:text-foreground">
                        {group.name}
                      </h3>
                      {group.description && (
                        <p className="text-xs text-foreground/50 mt-1 line-clamp-2">{group.description}</p>
                      )}
                    </div>
                    {group.lead_agent && (
                      <span className="text-xl ml-2 shrink-0" title={group.lead_agent.name}>
                        {group.lead_agent.avatar || '🤖'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-foreground/40">
                    <span className="inline-flex items-center gap-1">
                      <UsersIcon className="h-3 w-3" />
                      {group.member_count} 成员
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <MessageSquareIcon className="h-3 w-3" />
                      {group.message_count} 消息
                    </span>
                    {group.task_count > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-foreground/30" />
                        {group.done_task_count}/{group.task_count} 任务
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
