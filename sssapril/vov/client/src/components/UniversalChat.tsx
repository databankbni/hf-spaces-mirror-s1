/**
 * UniversalChat —— 全局召唤的通用对话侧边栏
 *
 * 设计目标（见 docs/product-evolution-discussion.md 决策 4/7）：
 * - 随 URL 切换的通用群聊组件，支持单/多 agent
 * - 侧边栏形态（Cmd/Ctrl+K 收放），主区域保持当前状态不被打断
 * - 复用 useChatStream + ChainBlock，引导 project 提供 groupId
 *
 * 数据流（T7）：
 *   guideApi.ensure() → group_id
 *   useGroup(group_id) → group（含 members）
 *   useChainViews({ groupId }) → taskChainViews + refreshLatestTaskChain
 *   useChatStream({...}) → activeReplyChain + handleSend + isStreaming
 */

import { useEffect, useState, useRef, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppStore, CHAT_HOTKEY_OPTIONS, type ChatHotkey } from '@/store/appStore';
import { guideApi, type GuideState } from '@/api/guide';
import { matchGuideRoute } from '@/lib/guideRouter';
import { useGroup } from '@/hooks/useGroups';
import { useChainViews } from '@/hooks/useChainViews';
import { useChatStream } from '@/hooks/useChatStream';
import ChainBlock from '@/components/chain/ChainBlock';
import { XIcon, SendIcon, SparklesIcon, SquareIcon, KeyboardIcon } from 'lucide-react';

/** 获取快捷键显示标签 */
const hotkeyLabel = (key: ChatHotkey) =>
  CHAT_HOTKEY_OPTIONS.find(o => o.key === key)?.label ?? `⌘${key.toUpperCase()}`;

/** 侧边栏宽度配置（可拖动改变） */
const DEFAULT_WIDTH = 520;
const MIN_WIDTH = 360;
const MAX_WIDTH = 960;
const WIDTH_STORAGE_KEY = 'universal-chat-width';

export const UniversalChat = () => {
  const open = useAppStore((s) => s.universalChatOpen);
  const toggle = useAppStore((s) => s.toggleUniversalChat);
  const setOpen = useAppStore((s) => s.setUniversalChatOpen);
  const chatHotkey = useAppStore((s) => s.chatHotkey);
  const setChatHotkey = useAppStore((s) => s.setChatHotkey);

  // 侧边栏宽度（可拖动，持久化到 localStorage）
  const [width, setWidth] = useState<number>(() => {
    if (typeof window === 'undefined') return DEFAULT_WIDTH;
    const saved = Number(localStorage.getItem(WIDTH_STORAGE_KEY));
    return saved && saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : DEFAULT_WIDTH;
  });
  const draggingRef = useRef(false);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const newWidth = window.innerWidth - e.clientX;
      setWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, newWidth)));
    };
    const onMouseUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem(WIDTH_STORAGE_KEY, String(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - lastMouseXRef.current))));
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, []);
  const lastMouseXRef = useRef(0);
  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    lastMouseXRef.current = e.clientX;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const [guide, setGuide] = useState<GuideState | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);

  // L0/L1 路由匹配：根据当前 URL 决定 guide 上下文
  const location = useLocation();
  const routeMatch = matchGuideRoute(location.pathname);
  const projectId = routeMatch.params.id as string | undefined;
  // guideKey: L0 用 'L0'，L1 用 'L1:<projectId>'，切换时触发重新 ensure
  const guideKey = routeMatch.level === 'L1' && projectId ? `L1:${projectId}` : 'L0';

  const groupId = guide?.group_id;

  // 1. 查询 group（含 members）—— useChatStream 的核心数据源
  const { data: group, isLoading: groupLoading } = useGroup(groupId || '');

  // 2. chain views 管理（历史消息 + 流式结束后刷新）
  const {
    taskChainViews,
    chainViewCache,
    loadGroupChains,
    refreshLatestTaskChain,
    handleLoadSubChain,
  } = useChainViews({ groupId });

  // 派生 members / agentList（useMemo 避免流式时每帧重建，依赖 group 引用稳定）
  const members = group?.members || [];
  const agentList = useMemo(() =>
    (group?.members || [])
      .filter((m: { agent?: { id: string; name: string; avatar?: string | null } }) => m.agent)
      .map((m: { agent: { id: string; name: string; avatar?: string | null } }) => ({
        id: m.agent.id,
        name: m.agent.name,
        avatar: m.agent.avatar,
      })),
    [group]
  );

  // 3. useChatStream —— 流式对话核心
  const {
    activeReplyChain,
    isStreaming,
    handleSend: streamSend,
    handleStopStream,
  } = useChatStream({
    groupId,
    group,
    members,
    agentList,
    taskChainViews,
    chainViewCache,
    refreshLatestTaskChain,
  });

  // Cmd/Ctrl+{chatHotkey} 收放
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === chatHotkey) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [toggle, chatHotkey]);

  // guideKey 变化时（L0↔L1 或切换项目）清空旧 guide，触发重新 ensure
  const lastGuideKeyRef = useRef<string>('');
  useEffect(() => {
    if (lastGuideKeyRef.current === guideKey) return;
    lastGuideKeyRef.current = guideKey;
    setGuide(null);
    setError(null);
  }, [guideKey]);

  // 幂等初始化引导（L0 调 ensure, L1 调 ensureProject）
  useEffect(() => {
    if (!open || guide || guideLoading) return;
    setGuideLoading(true);
    setError(null);
    const promise = routeMatch.level === 'L1' && projectId
      ? guideApi.ensureProject(projectId)
      : guideApi.ensure();
    promise
      .then((res) => setGuide(res.data))
      .catch((err) => setError(err?.message || '引导初始化失败'))
      .finally(() => setGuideLoading(false));
  }, [open, guide, guideLoading, routeMatch.level, projectId]);

  // group 加载完后加载 chains（与 ChatPage 一致的守卫）
  useEffect(() => {
    if (groupLoading || !groupId) return;
    loadGroupChains();
  }, [loadGroupChains, groupId, groupLoading]);

  // 消息变化时滚动到底部
  const messagesEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [taskChainViews, activeReplyChain]);

  const handleSend = () => {
    if (!draft.trim() || isStreaming) return;
    streamSend(draft, undefined, setSending);
    setDraft('');
  };

  const hasMessages = taskChainViews.length > 0 || activeReplyChain;

  return (
    <>
      {/* 收起时的浮动触发按钮 —— newspaper 风格：浅底 + 细边框 */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full border border-foreground/25 bg-background/95 px-4 py-3 text-sm font-medium text-foreground shadow-md backdrop-blur-sm transition hover:border-foreground/40 hover:bg-foreground/5"
          title={`召唤助手 (${hotkeyLabel(chatHotkey)})`}
        >
          <SparklesIcon className="h-4 w-4" />
          <span>召唤助手</span>
          <kbd className="ml-1 rounded border border-foreground/20 bg-foreground/5 px-1.5 py-0.5 text-[10px] text-foreground/70">{hotkeyLabel(chatHotkey)}</kbd>
        </button>
      )}

      {/* 侧边栏本体（浮层式，translate-x 控制收放） */}
      <aside
        className="fixed right-0 top-0 z-50 flex h-full flex-col border-l border-foreground/15 bg-background shadow-2xl transition-transform duration-300 ease-out"
        style={{
          width,
          transform: open ? 'translateX(0)' : 'translateX(100%)',
        }}
      >
        {/* 拖动改变宽度的 handle（左边缘竖条） */}
        <div
          onMouseDown={startDrag}
          className="absolute left-0 top-0 z-10 h-full w-1 cursor-col-resize hover:bg-foreground/30 hover:w-1.5 transition-all"
          title="拖动改变宽度"
        />
        {/* 标题栏 */}
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xl">{guide?.agent_avatar || '🧭'}</span>
            <div>
              <div className="text-sm font-semibold leading-tight">
                {guide?.agent_name || '引导助手'}
              </div>
              <div className="text-[11px] text-muted-foreground leading-tight">
                {guideLoading
                  ? '初始化中…'
                  : guide
                    ? isStreaming
                      ? '正在思考…'
                      : '在线 · 随时帮你'
                    : '准备中'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {/* 快捷键切换 */}
            <div className="group/hotkey relative">
              <button
                className="rounded-md p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                title="切换快捷键"
              >
                <KeyboardIcon className="h-4 w-4" />
              </button>
              <div className="absolute right-0 top-full mt-1 hidden group-hover/hotkey:block z-20">
                <div className="rounded-md border border-foreground/15 bg-background shadow-lg py-1 min-w-[100px]">
                  {CHAT_HOTKEY_OPTIONS.map(opt => (
                    <button
                      key={opt.key}
                      onClick={() => setChatHotkey(opt.key)}
                      className={`w-full px-3 py-1.5 text-left text-xs transition hover:bg-muted ${
                        chatHotkey === opt.key ? 'text-foreground font-semibold' : 'text-foreground/60'
                      }`}
                    >
                      {opt.label}
                      {chatHotkey === opt.key && ' ✓'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
              title={`收起 (${hotkeyLabel(chatHotkey)})`}
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* 错误提示 */}
        {error && (
          <div className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {/* 加载中 */}
          {(guideLoading || (groupLoading && !hasMessages)) && (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {guideLoading ? '正在准备引导环境…' : '加载对话中…'}
            </div>
          )}

          {/* 空状态欢迎 */}
          {!guideLoading && !groupLoading && !hasMessages && guide && (
            <div className="space-y-3 px-1 pt-4">
              <div className="flex gap-2">
                <span className="text-lg shrink-0">{guide.agent_avatar || '🧭'}</span>
                <div className="rounded-2xl rounded-tl-sm bg-muted px-3 py-2 text-sm">
                  {routeMatch.level === 'L1' ? (
                    <>
                      你好！我是项目总控。告诉我你想怎么开工，我帮你建群聊、分方向、规划流程。
                      <br />
                      <span className="text-muted-foreground">
                        例如："先建个需求讨论组"、"我想分三步走：构思→创作→审校"。
                      </span>
                    </>
                  ) : (
                    <>
                      你好！我是你的引导助手。告诉我你想做什么，我帮你建项目、配流程。
                      <br />
                      <span className="text-muted-foreground">
                        例如："我想写个武侠小说"、"帮我建个数据分析项目"。
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* 历史链 + 流式回复 */}
          {taskChainViews.map((view) => (
            <ChainBlock
              key={view.chain.id}
              view={view}
              agentList={agentList}
              externalSubChainViews={chainViewCache}
              onLoadSubChain={handleLoadSubChain}
            />
          ))}
          {activeReplyChain && (
            <ChainBlock
              view={activeReplyChain}
              liveStream
              agentList={agentList}
              externalSubChainViews={chainViewCache}
              onLoadSubChain={handleLoadSubChain}
            />
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入框 */}
        <footer className="border-t p-3">
          <div className="flex items-end gap-2 rounded-xl border bg-background px-3 py-2 focus-within:ring-1 focus-within:ring-ring">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="说说你想做什么… (Enter 发送 / Shift+Enter 换行)"
              rows={1}
              className="max-h-32 flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {isStreaming || sending ? (
              <button
                onClick={handleStopStream}
                className="rounded-lg bg-destructive p-1.5 text-destructive-foreground transition hover:opacity-90"
                title="停止生成"
              >
                <SquareIcon className="h-4 w-4" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!draft.trim() || !groupId}
                className="rounded-lg bg-primary p-1.5 text-primary-foreground transition hover:opacity-90 disabled:opacity-40"
                title="发送"
              >
                <SendIcon className="h-4 w-4" />
              </button>
            )}
          </div>
          <div className="mt-1.5 text-center text-[10px] text-muted-foreground">
            按 <kbd className="rounded bg-muted px-1">{hotkeyLabel(chatHotkey)}</kbd> 收起 · 点击 <KeyboardIcon className="inline h-3 w-3" /> 切换快捷键
          </div>
        </footer>
      </aside>
    </>
  );
};

export default UniversalChat;
