/**
 * ChainBlock 可折叠链条块组件
 *
 * 以层级折叠的链条块形式展示 Chain + Packet 数据。
 * - 折叠状态：仅显示链头/链尾包摘要
 * - 展开状态：显示所有包，子链嵌套显示
 */

import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import {
  ChevronDownIcon, ChevronRightIcon, BotIcon, UserIcon,
  WrenchIcon, AlertCircleIcon, BrainIcon, MessageSquareIcon,
  Loader2Icon, CheckCircleIcon, XCircleIcon, GitBranchIcon,
  DatabaseIcon, CopyIcon, HashIcon,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate } from 'react-router-dom';
import type { ChainView, Packet, PacketType, ChainType, ChainStatus } from '../../types';
import RenderEngine from '../../render-engine/RenderEngine';
import type { RenderSpec } from '../../render-engine/types';
import { parseThinkContent, getAgentEmoji, ToolCallRenderer, DataViewExpandButton, type ToolCallInfo, type ContentSegment } from '../chat/chatShared';
import { useAppStore } from '../../store/appStore';

// ─── 链类型配置 ────────────────────────────────────────────────

const chainTypeConfig: Record<ChainType, { label: string; icon: typeof GitBranchIcon; color: string; badge: string }> = {
  group: { label: '群', icon: MessageSquareIcon, color: 'text-foreground/50', badge: 'border border-foreground/15 text-foreground/60' },
  task: { label: '任务', icon: GitBranchIcon, color: 'text-foreground/50', badge: 'border border-foreground/15 text-foreground/60' },
  reply: { label: '回复', icon: BotIcon, color: 'text-foreground/50', badge: 'border border-foreground/15 text-foreground/60' },
  tool: { label: '工具', icon: WrenchIcon, color: 'text-foreground/50', badge: 'border border-foreground/15 text-foreground/60' },
};

const chainStatusIcon: Record<ChainStatus, { icon: typeof Loader2Icon; color: string; label: string }> = {
  active: { icon: Loader2Icon, color: 'text-emerald-600/80 animate-spin', label: '进行中' },
  pending: { icon: Loader2Icon, color: 'text-foreground/40', label: '待开始' },
  paused: { icon: Loader2Icon, color: 'text-amber-600/70', label: '已挂起' },
  completed: { icon: CheckCircleIcon, color: 'text-foreground/40', label: '已完成' },
  archived: { icon: CheckCircleIcon, color: 'text-foreground/30', label: '已归档' },
  failed: { icon: XCircleIcon, color: 'text-destructive/70', label: '失败' },
};

/**
 * 判断 chain 是否"当前活跃"——应默认展开 + 加视觉强调
 *   - active/pending: 用户正在关注的工作面
 *   - paused:         主链被任务接管期间是挂起状态，但用户视线应放在 task chain 上，
 *                     主链保持折叠是合适的 (因为它只是"任务开始时的快照")
 *   - completed/archived/failed: 历史快照，默认折叠
 */
function isChainLive(status: ChainStatus): boolean {
  return status === 'active' || status === 'pending';
}

// ─── Markdown 组件配置 ─────────────────────────────────────────

const mdComponents: Parameters<typeof ReactMarkdown>[0]['components'] = {
  h1: ({ children }) => <h1 className="text-lg font-bold mt-3 mb-1">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-bold mt-2.5 mb-0.5">{children}</h2>,
  h3: ({ children }) => <h3 className="text-base font-semibold mt-2 mb-0.5">{children}</h3>,
  p: ({ children }) => <p className="text-base leading-relaxed my-0.5">{children}</p>,
  ul: ({ children }) => <ul className="text-base list-disc pl-4 my-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="text-base list-decimal pl-4 my-0.5">{children}</ol>,
  li: ({ children }) => <li className="text-base leading-relaxed">{children}</li>,
  code: ({ className, children, ...props }) => {
    const isInline = !className;
    return isInline
      ? <code className="text-sm bg-muted px-1 py-0.5 rounded font-mono" {...props}>{children}</code>
      : <code className={`text-sm block bg-muted/50 p-2 rounded-md overflow-x-auto font-mono ${className || ''}`} {...props}>{children}</code>;
  },
  pre: ({ children }) => <pre className="my-1 overflow-x-auto">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/30 pl-3 my-1 text-muted-foreground">{children}</blockquote>,
};

// ─── PacketRenderer ────────────────────────────────────────────

interface PacketRendererProps {
  packet: Packet;
  /** 是否为流式中的包（显示光标） */
  streaming?: boolean;
  /** 流式显示的内容 */
  displayedContent?: string;
  /** 子链视图（如果包触发了子链） */
  subChainView?: ChainView;
  /** 加载子链的回调 */
  onLoadSubChain?: (chainId: string) => void;
  /** agent 列表（用于头像映射） */
  agentList?: Array<{ id: string; name: string; avatar?: string | null }>;
  /** 外部提供的子链视图缓存 */
  externalSubChainViews?: Record<string, ChainView>;
  /** 需要强制展开的 chain ID 集合（用户从侧边栏点击 task 跳转时用） */
  forceExpandedChainIds?: Set<string>;
}

/** 脚本注入块 — Agent 注入的 JS 代码
 *
 *  v3：
 *    - 首次挂载自动执行（用 runOnceRef 防 StrictMode 双跑）
 *    - 用 MutationObserver 追踪 eval() 期间新增到 document.body 的 DOM 元素，
 *      显示「已添加 N 个元素」反馈，并支持"取消注入"时一键从 DOM 移除
 *    - 取消状态写入 localStorage（key = page_inject_cancelled_<packetId>），
 *      再次进入聊天或刷新页面都不会再自动执行
 *    - 提供"重新执行"和"恢复注入"按钮
 *
 *  注意：eval() 添加的元素在**当前页面 DOM**（如 document.body），
 *  不会出现在聊天消息里。看代码看聊天，看页面效果看 DOM。
 */
function InjectJsBlock({ code, description, packetId }: { code: string; description: string; packetId: string }) {
  // 三态：pending（未跑）/ executed（跑过）/ cancelled（用户取消，后续不再自动跑）
  const [status, setStatus] = useState<'pending' | 'executed' | 'cancelled'>('pending');
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addedCount, setAddedCount] = useState(0);
  // 默认折叠 — 点标题可展开查看脚本与按钮
  const [expanded, setExpanded] = useState(false);

  // 追踪 eval() 期间通过 appendChild 等方式添加到 document.body 的 Element 节点，
  // 取消注入时能精确地把这些元素从 DOM 移除
  const trackedElementsRef = useRef<Element[]>([]);
  // 挂载即跑（防 StrictMode 双跑）
  const runOnceRef = useRef(false);

  const cancelStorageKey = `page_inject_cancelled_${packetId}`;

  // 检查 localStorage：曾经被取消过的话不自动跑
  useEffect(() => {
    if (runOnceRef.current) return;
    runOnceRef.current = true;
    if (typeof window !== 'undefined' && localStorage.getItem(cancelStorageKey) === 'true') {
      setStatus('cancelled');
      return;
    }
    execute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * 判断一个 DOM 节点是否是 React 管理的（React 18 会在节点上挂 __reactFiber$xxx / __reactContainer$xxx）。
   * 这类节点不能由我们手动 removeChild，否则 React 在后续 commit 阶段会因为找不到子节点而抛 NotFoundError。
   */
  function isReactManaged(el: Element): boolean {
    for (const key in el) {
      if (key.startsWith('__reactFiber$') || key.startsWith('__reactContainer$')) {
        return true;
      }
    }
    return false;
  }

  /**
   * 判断节点是否在某个 React 树的子树内（祖先里有 React 管理的节点，如 portal/root 元素）。
   * 这种情况也不应被我们移除。
   */
  function isInsideReactTree(el: Element): boolean {
    let cur: Element | null = el;
    while (cur && cur !== document.documentElement) {
      if (isReactManaged(cur)) return true;
      cur = cur.parentElement;
    }
    return false;
  }

  function execute() {
    // 清掉上一次的追踪
    trackedElementsRef.current = [];

    // 用 MutationObserver 收集本次执行期间新增到 body 的 Element 节点
    // 过滤掉 React 自身管理的节点（modal portal、preload trigger、下载 <a> 等），
    // 否则取消注入时会误删 React 的子节点，触发 commitDeletionEffectsOnFiber 抛 NotFoundError。
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of Array.from(m.addedNodes)) {
          if (node.nodeType !== 1) continue;
          const el = node as Element;
          if (isReactManaged(el)) continue;
          if (isInsideReactTree(el)) continue;
          trackedElementsRef.current.push(el);
        }
      }
    });
    try {
      observer.observe(document.body, { childList: true, subtree: true });
    } catch {
      // body 不存在时静默忽略
    }

    try {
      // eslint-disable-next-line no-eval
      const ret = eval(code);
      setStatus('executed');
      setError(null);
      // 给一个 tick 让 MutationObserver 收到最后一批回调
      setTimeout(() => {
        observer.disconnect();
        setAddedCount(trackedElementsRef.current.length);
      }, 0);
      if (ret !== undefined) {
        setResult(String(ret));
      }
    } catch (err) {
      observer.disconnect();
      setError(String(err));
      setStatus('executed');
    }
  }

  function removeTracked() {
    for (const el of trackedElementsRef.current) {
      // 三重防御：节点可能被外部移除、可能不在原父节点下、可能根本不是 Element
      if (!el || !el.parentNode) continue;
      if (isReactManaged(el)) continue;
      // 只移除仍在 tracked 父节点链下的真正子节点
      let parent: Node | null = el.parentNode;
      try {
        if (parent && parent.nodeType === 1) {
          const parentEl = parent as Element;
          // 二次确认：el 确实是 parentEl 的子节点
          if (parentEl.contains(el) && !isInsideReactTree(parentEl)) {
            parentEl.removeChild(el);
          }
        }
      } catch {
        // 已被外部移除或被 React 接管时静默忽略
      }
    }
    trackedElementsRef.current = [];
  }

  function handleReRun() {
    // 先把上次添加的元素从 DOM 移除
    removeTracked();
    setResult(null);
    setError(null);
    setAddedCount(0);
    execute();
  }

  function handleCancel() {
    // 从 DOM 移除本次注入的所有元素
    removeTracked();
    setAddedCount(0);
    setStatus('cancelled');
    try {
      localStorage.setItem(cancelStorageKey, 'true');
    } catch {
      // localStorage 不可用时静默忽略
    }
  }

  function handleRestore() {
    // 恢复注入：清掉取消标记 + 立即跑一次
    try {
      localStorage.removeItem(cancelStorageKey);
    } catch {
      // ignore
    }
    execute();
  }

  return (
    <div
      className="my-1 w-fit max-w-full rounded-lg border border-foreground/15 bg-foreground/[0.02] group overflow-hidden"
      style={{ maxWidth: 'min(100%, 560px)' }}
    >
      {/* 标题栏 — 点击切换展开/折叠 */}
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1 text-xs text-foreground/60 hover:text-foreground/80 transition-colors text-left"
        aria-expanded={expanded}
        title={expanded ? '收起脚本与操作' : '展开查看脚本与操作'}
      >
        <WrenchIcon className="w-3 h-3 flex-shrink-0" />
        <span className="font-newspaper-bold">page_inject</span>
        {description && (
          <span className="text-foreground/40 truncate max-w-[200px]">({description})</span>
        )}
        {status === 'executed' && !error && addedCount > 0 && (
          <span className="text-foreground/40 ml-1">· 已添加 {addedCount} 个元素</span>
        )}
        {status === 'executed' && !error && (
          <span className="text-emerald-600/80">✓</span>
        )}
        {status === 'cancelled' && (
          <span className="text-foreground/40">已取消</span>
        )}
        {error && (
          <span className="text-destructive">✗</span>
        )}
        <ChevronDownIcon
          className={`w-3 h-3 ml-auto flex-shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {expanded && (
        <div className="px-2.5 pb-2 border-t border-foreground/10 pt-1.5 space-y-1.5">
          <pre className="text-xs font-newspaper text-foreground/60 border border-foreground/10 p-1.5 overflow-x-auto max-h-32 whitespace-pre-wrap bg-foreground/[0.02]">{code}</pre>
          <div className="flex items-center gap-3 flex-wrap">
            {status !== 'cancelled' && (
              <button
                onClick={handleReRun}
                className="px-2 py-0.5 text-xs font-newspaper text-foreground/70 hover:text-foreground/90 underline-offset-2 hover:underline transition-all"
              >
                重新执行
              </button>
            )}
            {status === 'executed' && (
              <button
                onClick={handleCancel}
                className="px-2 py-0.5 text-xs font-newspaper text-destructive/80 hover:text-destructive underline-offset-2 hover:underline transition-all"
                title="从页面移除注入的元素，并在当前浏览器停止自动执行"
              >
                取消注入
              </button>
            )}
            {status === 'cancelled' && (
              <button
                onClick={handleRestore}
                className="px-2 py-0.5 text-xs font-newspaper text-foreground/70 hover:text-foreground/90 underline-offset-2 hover:underline transition-all"
                title="恢复后下次进入聊天或点击会重新执行"
              >
                恢复注入
              </button>
            )}
            {result && <span className="text-xs font-newspaper text-foreground/40">返回: {result}</span>}
            {error && <span className="text-xs font-newspaper text-destructive">{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 子链内联渲染 —— 从 PacketRenderer 中解耦的通用组件
 *
 * 设计原因：sub_chain_id 是 packet 级属性，不绑定特定 packet_type。
 * 后端在 task chain 创建/结束时往主链插入 system packet（带 sub_chain_id），
 * agent 回复也可能挂 reply/tool 子链。本组件统一处理所有 packet 类型的子链渲染。
 *
 * 渲染规则：
 *   - task chain: 始终内联渲染（在主链 packet 位置），active/pending 默认展开
 *   - reply/tool chain: 折叠到"查看过程"按钮后（过程是次要的）
 */
function SubChainInline({ packet, subChainView, onLoadSubChain, agentList, externalSubChainViews, forceExpandedChainIds }: {
  packet: Packet;
  subChainView?: ChainView;
  onLoadSubChain?: (chainId: string) => void;
  agentList?: Array<{ id: string; name: string; avatar?: string | null }>;
  externalSubChainViews?: Record<string, ChainView>;
  forceExpandedChainIds?: Set<string>;
}) {
  const [subChainExpanded, setSubChainExpanded] = useState(false);
  if (!packet.sub_chain_id) return null;

  if (subChainView?.chain?.chain_type === 'task') {
    return (
      <div className="mt-1 ml-2 border-l-2 border-primary/20 pl-2">
        <ChainBlock
          view={subChainView}
          defaultExpanded={subChainView.chain.status === 'active' || subChainView.chain.status === 'pending'}
          forceExpanded={forceExpandedChainIds?.has(subChainView.chain.id)}
          onLoadSubChain={onLoadSubChain}
          agentList={agentList}
          externalSubChainViews={externalSubChainViews}
          depth={1}
          forceExpandedChainIds={forceExpandedChainIds}
        />
      </div>
    );
  }

  // reply/tool chain: 折叠到"查看过程"按钮
  return (
    <div className="mt-1 ml-2">
      <button
        onClick={() => {
          if (onLoadSubChain && packet.sub_chain_id) {
            onLoadSubChain(packet.sub_chain_id);
          }
          setSubChainExpanded(!subChainExpanded);
        }}
        className="text-xs font-newspaper text-foreground/50 hover:text-foreground/70 flex items-center gap-1 underline-offset-2 hover:underline transition-all"
      >
        <GitBranchIcon className="w-3 h-3" />
        {subChainExpanded ? '收起过程' : '查看过程'}
      </button>
      {subChainExpanded && subChainView && (
        <div className="mt-1 ml-2 border-l-2 border-primary/20 pl-2">
          <ChainBlock view={subChainView} onLoadSubChain={onLoadSubChain} agentList={agentList} externalSubChainViews={externalSubChainViews} depth={1} />
        </div>
      )}
    </div>
  );
}

/**
 * Think 块渲染 —— 流式 & 完成的思考过程统一组件
 *
 * 流式时默认展开（用户能实时看到思考过程），思考完成自动折叠（精简界面）。
 * 用户手动展开/折叠后，后续不再自动改变状态。
 */
function ThinkBlock({ content, isStreaming }: { content: string; isStreaming: boolean }) {
  const [open, setOpen] = useState(isStreaming);
  const wasStreamingRef = useRef(isStreaming);
  useEffect(() => {
    // 流式结束的瞬间自动折叠一次（用户手动展开后不再受影响）
    if (wasStreamingRef.current && !isStreaming) {
      setOpen(false);
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      className="my-1 group"
    >
      <summary className="flex items-center gap-1.5 px-1 py-0.5 text-sm text-foreground/40 cursor-pointer select-none hover:text-foreground/60 transition-colors font-newspaper">
        <BrainIcon className={`w-3 h-3 ${isStreaming ? 'animate-pulse' : ''}`} />
        <span className="font-newspaper-bold">{isStreaming ? '思考中…' : '思考过程'}</span>
        <ChevronDownIcon className="w-3 h-3 ml-1 opacity-50 transition-transform group-open:rotate-180" />
      </summary>
      <div className="pl-4 text-sm text-foreground/40 whitespace-pre-wrap leading-relaxed border-l border-foreground/15 mt-0.5 pt-0.5">{content}</div>
    </details>
  );
}

function PacketRenderer({ packet, streaming, displayedContent, subChainView, onLoadSubChain, agentList, externalSubChainViews, forceExpandedChainIds }: PacketRendererProps) {
  const { packet_type, sender_type, sender_name, content, metadata } = packet;
  // 消息显示偏好: 优先用群级别覆盖, 回退到系统级设置。
  // 群级别覆盖 undefined = 继承系统; true/false = 强制覆盖。
  const showThink = useAppStore((s) => {
    if (!s.activeGroupId) return s.showThink;
    const ov = s.groupVisibilityOverrides[s.activeGroupId]?.showThink;
    return ov !== undefined ? ov : s.showThink;
  });
  const showToolCalls = useAppStore((s) => {
    if (!s.activeGroupId) return s.showToolCalls;
    const ov = s.groupVisibilityOverrides[s.activeGroupId]?.showToolCalls;
    return ov !== undefined ? ov : s.showToolCalls;
  });
  const showSystemMessages = useAppStore((s) => {
    if (!s.activeGroupId) return s.showSystemMessages;
    const ov = s.groupVisibilityOverrides[s.activeGroupId]?.showSystemMessages;
    return ov !== undefined ? ov : s.showSystemMessages;
  });

  // 关键：流式光标跟踪
  // 1) streaming prop 可能因 chain.status 没及时更新而残留 true
  // 2) displayedContent 长度追上 content 长度时= 打字完成
  // 3) 用 local "hasFinished" ref 一旦 typing 完成就永远关闭光标
  // 4) content 本身就是空时，绝对不显示光标（避免"空 packet + 残留 streaming"导致空白闪烁）
  // 5) 当 displayedContent 未提供时（直接流式追加模式），effectiveContent 直接用 content
  const isActivelyTyping = streaming
    && content.length > 0
    && (displayedContent == null || displayedContent.length < content.length);
  const effectiveContent = displayedContent != null ? displayedContent : content;
  const [hasFinished, setHasFinished] = useState(false);
  useEffect(() => {
    if (!isActivelyTyping) {
      // 一旦 typing 完成就锁定 hasFinished=true，永不再显示光标
      setHasFinished(true);
    } else {
      setHasFinished(false);
    }
  }, [isActivelyTyping]);

  // 解析 think 标签
  const segments = useMemo(() => parseThinkContent(effectiveContent), [effectiveContent]);

  // 工具调用信息
  const toolCalls = useMemo(() => {
    const raw = (metadata as Record<string, unknown>)?.tool_calls;
    if (!Array.isArray(raw) || raw.length === 0) return null;
    return raw as Array<{ tool_name: string; arguments: Record<string, unknown>; result?: unknown; tool_call_id?: string }>;
  }, [metadata]);

  // 工具调用穿插渲染: content 里的 <tool_call_pos /> 标记按出现顺序对应 metadata.tool_calls.
  // toolCallPositions[i] = 第 i 个 segment 如果是 tool_call_pos, 对应 toolCalls 数组的索引; 否则 -1.
  // 多轮调用 (tool → result → 再 stream) 时, 后端 stream_process 在每轮 has_tool_calls 时
  // 推送标记, StreamPushPlugin 累积到同一 content, 时序天然正确.
  const toolCallPositions = useMemo(() => {
    let idx = 0;
    return segments.map(seg => (seg.type === 'tool_call_pos' ? idx++ : -1));
  }, [segments]);

  // 被 tool_call_pos 标记消费的工具调用数量; 剩余的回退到末尾渲染 (兜底老数据/core_process 路径)
  const consumedToolCallCount = useMemo(() => {
    return toolCallPositions.filter(i => i >= 0).length;
  }, [toolCallPositions]);

  const trailingToolCalls = useMemo(() => {
    if (!toolCalls) return null;
    const remaining = toolCalls.slice(consumedToolCallCount);
    return remaining.length > 0 ? remaining : null;
  }, [toolCalls, consumedToolCallCount]);

  // render_spec 数据视图配置（优先从顶层取，兼容旧数据从 tool_calls 中提取）
  // 支持单个 RenderSpec 或数组（多个 render_view 调用）
  const renderSpecs = useMemo((): RenderSpec[] => {
    const meta = metadata as Record<string, unknown>;
    const spec = meta?.render_spec;

    // 顶层 render_spec 可能是单个对象或数组
    if (spec) {
      if (Array.isArray(spec)) return spec as RenderSpec[];
      if (typeof spec === 'object') return [spec as RenderSpec];
    }

    // 兼容旧数据：从 tool_calls 中提取所有 render_view 的参数
    const toolCalls = meta?.tool_calls;
    if (Array.isArray(toolCalls)) {
      const renderCalls = toolCalls.filter((tc: Record<string, unknown>) => tc.tool_name === 'render_view');
      // 优先使用 tool_call 中的 render_spec（新数据），否则用 arguments（旧数据）
      const specs = renderCalls.map((tc: Record<string, unknown>) => {
        if (tc.render_spec && typeof tc.render_spec === 'object') return tc.render_spec as RenderSpec;
        if (tc.arguments && typeof tc.arguments === 'object') return tc.arguments as RenderSpec;
        return null;
      }).filter((s): s is RenderSpec => s !== null);
      if (specs.length > 0) return specs;
    }

    return [];
  }, [metadata]);

  // 用户消息
  if (packet_type === 'user_input') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%]">
          <div className="text-sm text-muted-foreground mb-0.5 text-right px-1">{sender_name}</div>
          <div className="px-2 py-1 text-foreground text-base whitespace-pre-wrap">
            {effectiveContent}
          </div>
        </div>
      </div>
    );
  }

  // 系统消息（task chain 入口 packet 也是 system 类型, 需渲染子链）
  if (packet_type === 'system') {
    // 用户在设置里关闭了系统消息: 隐藏 system 文本, 但仍渲染子链 (任务实际内容)
    if (!showSystemMessages) {
      return (
        <SubChainInline
          packet={packet}
          subChainView={subChainView}
          onLoadSubChain={onLoadSubChain}
          agentList={agentList}
          externalSubChainViews={externalSubChainViews}
          forceExpandedChainIds={forceExpandedChainIds}
        />
      );
    }
    // 所有 system packet 默认折叠, 显示第一行 (按 \n 分割), 点击展开看全部.
    // 第一行很长时由 CSS truncate 自然省略.
    const firstLine = effectiveContent.split('\n')[0] || '';
    return (
      <div>
        <details className="group">
          <summary className="flex justify-center items-center gap-1 px-3 py-0.5 text-xs text-muted-foreground/60 cursor-pointer select-none hover:text-muted-foreground transition-colors font-newspaper list-none">
            <ChevronRightIcon className="w-3 h-3 opacity-40 transition-transform group-open:rotate-90 flex-shrink-0" />
            <span className="truncate max-w-[600px]">{firstLine}</span>
          </summary>
          <div className="flex justify-center">
            <div className="px-3 py-0.5 text-sm text-muted-foreground/70 whitespace-pre-wrap">
              {effectiveContent}
            </div>
          </div>
        </details>
        <SubChainInline
          packet={packet}
          subChainView={subChainView}
          onLoadSubChain={onLoadSubChain}
          agentList={agentList}
          externalSubChainViews={externalSubChainViews}
          forceExpandedChainIds={forceExpandedChainIds}
        />
      </div>
    );
  }

  // 错误消息
  if (packet_type === 'error') {
    return (
      <div className="flex gap-1.5">
        <AlertCircleIcon className="w-3.5 h-3.5 text-destructive flex-shrink-0 mt-0.5" />
        <div className="text-base text-destructive/90">
          {effectiveContent}
        </div>
      </div>
    );
  }

  // 工具调用
  if (packet_type === 'tool_call') {
    // 用户在设置里关闭了工具调用显示: 完全隐藏
    if (!showToolCalls) return null;
    const toolName = (metadata as Record<string, unknown>)?.tool_name as string || 'unknown';
    return (
      <details className="my-0.5 w-fit max-w-full rounded-lg border border-foreground/15 bg-foreground/[0.02] group overflow-hidden" style={{ maxWidth: 'min(100%, 560px)' }}>
        <summary className="flex items-center gap-1.5 px-2.5 py-1 text-xs cursor-pointer select-none text-foreground/60 hover:text-foreground/80 transition-colors font-newspaper">
          <WrenchIcon className="w-3 h-3" />
          <span className="font-newspaper-bold">{toolName}</span>
          <ChevronDownIcon className="w-3 h-3 ml-auto transition-transform group-open:rotate-180 flex-shrink-0" />
        </summary>
        <div className="px-2.5 pb-1.5 border-t border-foreground/10 pt-1.5 text-sm text-foreground/70 max-h-96 overflow-y-auto">
          {effectiveContent && <pre className="whitespace-pre-wrap text-sm font-newspaper">{effectiveContent}</pre>}
        </div>
      </details>
    );
  }

  // 工具结果
  if (packet_type === 'tool_result') {
    // 用户在设置里关闭了工具调用显示: 工具结果也一起隐藏
    if (!showToolCalls) return null;
    return (
      <details className="my-0.5 w-fit max-w-full rounded-lg border border-foreground/15 bg-foreground/[0.02] group overflow-hidden" style={{ maxWidth: 'min(100%, 560px)' }}>
        <summary className="flex items-center gap-1.5 px-2.5 py-1 text-xs cursor-pointer select-none text-foreground/50 hover:text-foreground/70 transition-colors font-newspaper">
          <WrenchIcon className="w-3 h-3" />
          <span>工具结果</span>
          <ChevronDownIcon className="w-3 h-3 ml-auto transition-transform group-open:rotate-180 flex-shrink-0" />
        </summary>
        <div className="px-2.5 pb-1.5 border-t border-foreground/10 pt-1.5 text-sm text-foreground/60 max-h-96 overflow-y-auto whitespace-pre-wrap">
          {effectiveContent}
        </div>
      </details>
    );
  }

  // think 包
  if (packet_type === 'think') {
    // 用户在设置里关闭了 think 显示: 完全隐藏
    if (!showThink) return null;
    return <ThinkBlock content={effectiveContent} isStreaming={false} />;
  }

  // agent_text：主消息渲染
  const agentForMsg = sender_type === 'agent' ? agentList?.find(a => a.id === packet.sender_id) : null;

  // Bug fix: 关闭 think/tool_call 显示后, 如果整条 agent_text 的所有 segments 都被过滤掉
  // 且没有正文文本 + 非流式中, 则整条不渲染 (避免出现"头像+空消息"占位)
  // 场景: applyToolResult 创建的空 agent_text 占位包, 或 agent 只产 think+tool_call 没正文
  {
    const isStreamingPacket = !!(metadata as Record<string, unknown>)?.streaming;
    const hasVisibleSegment = segments.some(seg => {
      if (seg.type === 'think') return showThink;
      if (seg.type === 'tool_call_pos') return showToolCalls;
      return seg.content.trim().length > 0;
    });
    const hasTrailingToolCalls = trailingToolCalls && showToolCalls;
    const hasRenderSpecs = renderSpecs.length > 0;
    const hasInjectJs = !!(metadata as Record<string, unknown>)?.inject_js;
    const hasSubChain = !!subChainView;
    // 全部内容都被过滤掉, 且非流式中, 且没有 render_spec/inject_js/sub_chain → 整条不渲染
    if (!hasVisibleSegment && !hasTrailingToolCalls && !hasRenderSpecs && !hasInjectJs && !hasSubChain && !isStreamingPacket) {
      return null;
    }
  }

  return (
    <div className="group/pkt relative">
    <div className="flex gap-1.5">
      <div className="w-5 h-5 border border-foreground/15 flex items-center justify-center flex-shrink-0 text-sm mt-0.5">
        {sender_type === 'agent' ? getAgentEmoji(agentForMsg) : <UserIcon className="w-3 h-3 text-foreground/50" />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-newspaper text-foreground/40 mb-0.5 px-0.5">{sender_name}</div>
        <div className="text-base font-newspaper">
          {/* 按 segments 时序渲染 think + 文字 + 工具调用位置 (不再三段聚合) */}
          {/* parseThinkContent 已清理 think 标签和工具调用文本标记, text segment 是纯正文 */}
          {/* tool_call_pos segment 按出现顺序从 metadata.tool_calls 消费详情, 实现穿插渲染 */}
          {segments.map((seg, i) => {
            if (seg.type === 'think') {
              // 用户在设置里关闭了 think 显示时, 跳过 ThinkBlock 渲染
              return showThink ? <ThinkBlock key={i} content={seg.content} isStreaming={!seg.complete} /> : null;
            }
            if (seg.type === 'tool_call_pos') {
              // 用户关闭了工具调用显示: 跳过
              if (!showToolCalls) return null;
              const posIdx = toolCallPositions[i];
              const tc = toolCalls?.[posIdx];
              if (!tc) return null;
              return (
                <div key={i} className="mt-1 ml-0">
                  <ToolCallRenderer toolCalls={[tc]} />
                </div>
              );
            }
            const text = seg.content.trim();
            if (!text) return null;
            return (
              <div key={i}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{text}</ReactMarkdown>
              </div>
            );
          })}

          {/* content 完全为空时: 显示流式中 / 流式响应中断提示 */}
          {segments.length === 0 && packet_type === 'agent_text' && (metadata as Record<string, unknown>)?.streaming ? (
            // v3: 区分"流式中" vs "流式响应中断"
            //   - streaming prop=true  → 当前正在 attach 追踪中 (sending 或 resume 成功)
            //   - streaming prop=false → DB 残留 streaming 标记但后端无活跃流
            streaming ? (
              <div className="flex items-center gap-2 py-1 text-sm text-foreground/40 font-newspaper italic">
                <Loader2Icon className="w-3 h-3 animate-spin" />
                流式中…
              </div>
            ) : (
              <div className="flex items-center gap-2 py-1 text-sm text-foreground/30 font-newspaper italic">
                <Loader2Icon className="w-3 h-3 animate-spin" />
                流式响应中断，刷新页面可查看最新内容
              </div>
            )
          ) : null}

          {/* 数据视图渲染（render_spec） */}
          {renderSpecs.length > 0 && !streaming && (
            <div className="my-4 space-y-3">
              {renderSpecs.map((spec, idx) => {
                const viewLabel = spec.view_type ? spec.view_type.replace(/_/g, ' ') : 'data';
                const title = spec.title || viewLabel;
                return (
                  <details key={idx} open className="group border border-foreground/15 overflow-hidden rounded-md">
                    <summary className="flex items-center gap-1.5 px-3 py-2 text-sm cursor-pointer select-none text-foreground/50 hover:text-foreground/70 transition-colors font-newspaper">
                      <DatabaseIcon className="w-3 h-3 flex-shrink-0" />
                      <span className="font-newspaper-bold">{title}</span>
                      <ChevronDownIcon className="w-3 h-3 ml-1 opacity-50 transition-transform group-open:rotate-180" />
                      <DataViewExpandButton spec={spec} />
                    </summary>
                    <div className="px-4 py-4 border-t border-foreground/10 bg-background/30">
                      <RenderEngine spec={spec} />
                    </div>
                  </details>
                );
              })}
            </div>
          )}

          {/* 脚本注入（inject_js） */}
          {(metadata as Record<string, unknown>)?.inject_js && !streaming && (
            <InjectJsBlock
              code={(metadata as Record<string, unknown>).inject_js as string}
              description={(metadata as Record<string, unknown>).inject_description as string || ''}
              packetId={packet.id}
            />
          )}

          {/* 流式光标 — 三重保险：1) 真在打字 2) 没完成 3) 非 think 段落 */}
          {isActivelyTyping && !hasFinished && !segments.some(s => s.type === 'think' && !s.complete) && (
            <span data-debug-caret className="inline-block w-0.5 h-5 bg-foreground/70 ml-0.5 animate-pulse align-text-bottom" data-streaming={String(streaming)} data-content-len={content.length} data-displayed-len={displayedContent?.length ?? -1} data-has-finished={String(hasFinished)} />
          )}

          {/* debug 注释：当前 caret 条件：isActivelyTyping && !hasFinished && !think */}
          {/* content 长度为 0 时，isActivelyTyping 必为 false，光标必不渲染 */}
        </div>

        {/* 末尾兜底: 渲染未被 <tool_call_pos /> 标记消费的剩余工具调用
            (老数据无位置标记, 或 core_process 路径未推送标记时, 全部工具调用在此渲染) */}
        {trailingToolCalls && showToolCalls && (
          <div className="mt-1 ml-0">
            <ToolCallRenderer toolCalls={trailingToolCalls} />
          </div>
        )}

        {/* 子链内联渲染（task chain / reply / tool chain 统一走 SubChainInline） */}
        <SubChainInline
          packet={packet}
          subChainView={subChainView}
          onLoadSubChain={onLoadSubChain}
          agentList={agentList}
          externalSubChainViews={externalSubChainViews}
          forceExpandedChainIds={forceExpandedChainIds}
        />
      </div>
    </div>
    <PacketActions content={effectiveContent} packetId={packet.id} />
    </div>
  );
}

// ─── PacketRenderer 内部的消息操作按钮 ──────────────────────────

function PacketActions({ content, packetId }: { content: string; packetId: string }) {
  return (
    <div className="opacity-0 group-hover/pkt:opacity-100 transition-opacity flex items-center gap-0.5 mt-0.5 px-1">
      <button
        className="p-1 text-foreground/30 hover:text-foreground/60 hover:bg-foreground/5 transition-colors"
        title="复制消息"
        onClick={() => navigator.clipboard.writeText(content).catch(() => {})}
      >
        <CopyIcon className="w-3 h-3" />
      </button>
      <button
        className="p-1 text-foreground/30 hover:text-foreground/60 hover:bg-foreground/5 transition-colors"
        title="复制消息 ID"
        onClick={() => navigator.clipboard.writeText(packetId).catch(() => {})}
      >
        <HashIcon className="w-3 h-3" />
      </button>
    </div>
  );
}

// ─── ChainBlock 主组件 ─────────────────────────────────────────

export interface ChainBlockProps {
  /** 链视图数据 */
  view: ChainView;
  /** 初始展开状态 */
  defaultExpanded?: boolean;
  /**
   * 强制展开（用户从侧边栏点击 task 跳过来时用）.
   * - 设为 true 时立即展开 (覆盖 defaultExpanded)
   * - 用户仍可手动折叠
   * - 不会重置用户后续的折叠操作
   */
  forceExpanded?: boolean;
  /** 加载子链的回调 */
  onLoadSubChain?: (chainId: string) => void;
  /** agent 列表 */
  agentList?: Array<{ id: string; name: string; avatar?: string | null }>;
  /** 嵌套层级（用于缩进和样式调整） */
  depth?: number;
  /** 外部提供的子链视图缓存（如 ChatPage 的 chainViewCache） */
  externalSubChainViews?: Record<string, ChainView>;
  /**
   * 是否为"正在流式中"的活跃回复链。
   * 只有这条链才允许显示打字光标；其他链（含 taskChainViews 中
   * 刚转入的同一条链）即使 status 仍为 'active'，也不再显示光标，
   * 避免"AI 回复完一行还在闪"的残留问题。
   */
  liveStream?: boolean;
  /** 需要强制展开的 chain ID 集合（用户从侧边栏点击 task 跳转时用），会下传给内联 task chain */
  forceExpandedChainIds?: Set<string>;
}

function ChainBlock({ view, defaultExpanded, forceExpanded, onLoadSubChain, agentList, depth = 0, externalSubChainViews, liveStream = false, forceExpandedChainIds }: ChainBlockProps) {
  const { chain, packets, sub_chains } = view;
  const [expanded, setExpanded] = useState(forceExpanded === true ? true : (defaultExpanded ?? (depth === 0)));
  const [loadedSubChains, setLoadedSubChains] = useState<Record<string, ChainView>>({});

  // v2 P2+: 用户从侧边栏点击 task 跳过来时，强制展开一次
  //   - 后续用户手动折叠不会被重置（只听 false→true 边沿）
  useEffect(() => {
    if (forceExpanded) {
      setExpanded(true);
    }
  }, [forceExpanded]);

  const cfg = chainTypeConfig[chain.chain_type] || chainTypeConfig.task;
  const StatusIcon = chainStatusIcon[chain.status]?.icon || CheckCircleIcon;
  const statusColor = chainStatusIcon[chain.status]?.color || 'text-muted-foreground';
  const statusLabel = chainStatusIcon[chain.status]?.label || chain.status;
  const live = isChainLive(chain.status);

  // 构建子链映射：packet.sub_chain_id -> ChainView
  // 优先级: 全量视图 (cache/loaded) > 摘要视图 (sub_chains head/tail)
  // sub_chains 里的摘要只有 head/tail 包, 不能用于内联渲染 task chain 内容
  const subChainMap = useMemo(() => {
    const map: Record<string, ChainView> = {};
    // 1. 先放摘要 (sub_chains 里的 head/tail 视图)
    for (const sc of sub_chains) {
      map[sc.chain.id] = sc;
    }
    // 2. 全量视图覆盖摘要 (cache 里的 task chain 全量视图, packets 完整)
    if (externalSubChainViews) {
      for (const [id, sv] of Object.entries(externalSubChainViews)) {
        const existing = map[id];
        if (!existing || (sv.packets?.length ?? 0) > (existing.packets?.length ?? 0)) {
          map[id] = sv;
        }
      }
    }
    // 3. 动态加载的子链 (用户点"查看过程"后异步拉取)
    for (const [id, sv] of Object.entries(loadedSubChains)) {
      const existing = map[id];
      if (!existing || (sv.packets?.length ?? 0) > (existing.packets?.length ?? 0)) {
        map[id] = sv;
      }
    }
    return map;
  }, [sub_chains, externalSubChainViews, loadedSubChains]);

  const handleLoadSubChain = useCallback(async (chainId: string) => {
    if (loadedSubChains[chainId]) return;
    if (onLoadSubChain) {
      onLoadSubChain(chainId);
    }
  }, [loadedSubChains, onLoadSubChain]);

  // 动态加载子链结果注入
  const injectLoadedSubChain = useCallback((chainId: string, view: ChainView) => {
    setLoadedSubChains(prev => ({ ...prev, [chainId]: view }));
  }, []);

  // 折叠时显示头尾摘要
  const headPacket = packets[0];
  const tailPacket = packets.length > 1 ? packets[packets.length - 1] : null;

  const isTaskOrGroup = chain.chain_type === 'task' || chain.chain_type === 'group';
  const isCompact = chain.chain_type === 'tool' || chain.chain_type === 'reply';

  return (
    <div
      className={`rounded-lg ${live ? 'border-l-2 border-emerald-500/60 pl-1.5' : 'border-l-2 border-transparent'}`}
      data-chain={chain.id}
      data-chain-status={chain.status}
    >
      {/* 链头 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center gap-2 px-2.5 py-1.5 transition-colors text-left font-newspaper ${
          live ? 'hover:bg-emerald-500/[0.04]' : 'hover:bg-foreground/5'
        }`}
      >
        {expanded ? (
          <ChevronDownIcon className="w-3 h-3 text-foreground/30 flex-shrink-0" />
        ) : (
          <ChevronRightIcon className="w-3 h-3 text-foreground/30 flex-shrink-0" />
        )}
        <cfg.icon className={`w-3 h-3 ${cfg.color} flex-shrink-0`} />
        <span className={`font-newspaper-bold opacity-70 text-[10px] ${cfg.badge}`}>
          {cfg.label}
        </span>
        {chain.description && (
          <span className={`text-xs font-newspaper truncate flex-1 ${live ? 'text-foreground/70' : 'text-foreground/50'}`}>
            {chain.description}
          </span>
        )}
        {/* 状态标签 —— 活跃链高亮，历史链淡化 */}
        <span
          className={`text-[10px] flex-shrink-0 font-newspaper px-1 py-px ${
            live
              ? 'text-emerald-700/80 bg-emerald-500/10'
              : 'text-foreground/35'
          }`}
          title={`状态: ${statusLabel}`}
        >
          {statusLabel}
        </span>
        <span className="text-[10px] text-foreground/30 flex-shrink-0 font-newspaper">
          {chain.packet_count} 包
          {chain.sub_chain_count > 0 && ` · ${chain.sub_chain_count} 子链`}
        </span>
        <StatusIcon className={`w-3 h-3 ${statusColor} flex-shrink-0`} />
      </button>

      {/* 折叠摘要 */}
      {!expanded && headPacket && (
        <div className="px-3 pb-2 pt-1 space-y-1 border-t border-foreground/10">
          <PacketSummary packet={headPacket} isLiveStream={live} />
          {tailPacket && tailPacket.id !== headPacket.id && (
            <>
              <div className="flex items-center px-2">
                <div className="w-px h-2 bg-foreground/20" />
              </div>
              <PacketSummary packet={tailPacket} isLiveStream={live} />
            </>
          )}
        </div>
      )}

      {/* 展开内容 */}
      {expanded && (
        <div data-chain-content className="px-3 pb-3 pt-1 space-y-2 border-t border-foreground/10">
          {packets.map((pkt, idx) => {
            // 最后一个 agent_text 包且链状态为 active 时标记为流式中
            // 但如果包已有 render_spec 数据（顶层或嵌套在 tool_calls 中），说明 agent 已完成工具调用，不应视为流式
            const meta = pkt.metadata as Record<string, unknown>;
            const hasRenderSpec = !!meta?.render_spec
              || (Array.isArray(meta?.tool_calls) && (meta.tool_calls as any[]).some((tc: any) => tc.render_spec));
            // 关键：只有"活跃回复链"才显示流式光标。
            // 一旦这条链被 refreshLatestTaskChain 转入 taskChainViews（无论后端 status 是不是 'active'），
            // liveStream 变为 false，光标就立即消失，根治"最后一行还在闪"。
            const isStreaming = liveStream
              && chain.status === 'active'
              && pkt.packet_type === 'agent_text'
              && idx === packets.length - 1
              && !hasRenderSpec;
            return (
              <PacketRenderer
                key={pkt.id}
                packet={pkt}
                streaming={isStreaming}
                subChainView={pkt.sub_chain_id ? subChainMap[pkt.sub_chain_id] : undefined}
                onLoadSubChain={handleLoadSubChain}
                agentList={agentList}
                externalSubChainViews={externalSubChainViews}
                forceExpandedChainIds={forceExpandedChainIds}
              />
            );
          })}
          {/* 工具调用期间：AI 正在执行工具或思考下一轮 */}
          {liveStream && chain.status === 'active' && packets.length > 0
            && (packets[packets.length - 1].packet_type === 'tool_call'
              || packets[packets.length - 1].packet_type === 'tool_result') && (
            <div className="flex items-center gap-2 py-1 text-xs text-foreground/40">
              <Loader2Icon className="w-3 h-3 animate-spin" />
              <span>{packets[packets.length - 1].packet_type === 'tool_call' ? '执行工具中…' : '思考中…'}</span>
            </div>
          )}
          {packets.length === 0 && chain.status === 'active' && (
            <div className="flex items-center gap-2 py-1.5 text-xs text-foreground/30">
              <Loader2Icon className="w-3 h-3 animate-spin" />
              等待响应…
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// memo 优化：流式 token 更新时，历史链的 ChainBlock props 不变可跳过 re-render
export default memo(ChainBlock);

// ─── PacketSummary（折叠时的摘要） ─────────────────────────────

function PacketSummary({ packet, isLiveStream = false }: { packet: Packet; isLiveStream?: boolean }) {
  const { packet_type, sender_name, content } = packet;
  const truncated = content.length > 80 ? content.slice(0, 80) + '…' : content;

  if (packet_type === 'user_input') {
    return (
      <div className="flex items-center gap-1.5 text-xs font-newspaper">
        <UserIcon className="w-3 h-3 text-foreground/40 flex-shrink-0" />
        <span className="text-foreground/40">{sender_name}:</span>
        <span className="text-foreground/60 truncate">{truncated}</span>
      </div>
    );
  }

  if (packet_type === 'agent_text') {
    // v3: 三种状态区分
    //   - 有内容: 直接显示 truncated
    //   - 无内容 + streaming=true + isLiveStream=true: 当前正在 attach 追踪中 (sending 或 resume)
    //     → 显示"流式中…"光标
    //   - 无内容 + streaming=true + isLiveStream=false: 后端无活跃流但 DB 残留 streaming 标记
    //     → 显示"流式响应中断" (兼容老行为)
    //   - 无内容 + streaming=false: 静默 (不应该出现, 但兜底)
    const isStreaming = !content && (packet.metadata as Record<string, unknown>)?.streaming;
    let label: string;
    if (content) {
      label = truncated;
    } else if (isStreaming) {
      label = isLiveStream ? '流式中…' : '流式响应中断';
    } else {
      label = '…';
    }
    return (
      <div className="flex items-center gap-1.5 text-xs font-newspaper">
        <BotIcon className="w-3 h-3 text-foreground/30 flex-shrink-0" />
        <span className="text-foreground/40">{sender_name}:</span>
        <span className="text-foreground/60 truncate">{label}</span>
      </div>
    );
  }

  if (packet_type === 'tool_call') {
    const toolName = (packet.metadata as Record<string, unknown>)?.tool_name as string || 'tool';
    return (
      <div className="flex items-center gap-1.5 text-xs text-foreground/50 font-newspaper">
        <WrenchIcon className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">调用 {toolName}</span>
      </div>
    );
  }

  if (packet_type === 'think') {
    return (
      <div className="flex items-center gap-1.5 text-xs text-foreground/40 font-newspaper">
        <BrainIcon className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">思考过程</span>
      </div>
    );
  }

  if (packet_type === 'error') {
    return (
      <div className="flex items-center gap-1.5 text-xs text-foreground/50 font-newspaper">
        <AlertCircleIcon className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">{truncated}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 text-xs text-foreground/40 font-newspaper">
      <MessageSquareIcon className="w-3 h-3 flex-shrink-0" />
      <span className="truncate">{truncated}</span>
    </div>
  );
}
