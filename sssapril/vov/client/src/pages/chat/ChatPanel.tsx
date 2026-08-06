import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import {
  SendIcon, BotIcon, MessageSquareIcon,
  StopCircleIcon, ArrowUpIcon, ArrowDownIcon,
  ChevronsUpIcon, ChevronsDownIcon, Loader2Icon,
} from 'lucide-react';
import { useChatPage } from './context';
import ChainBlock from '../../components/chain/ChainBlock';
import ResourcePanel from './ResourcePanel';
import { getAgentEmoji } from '../../components/chat/chatShared';

export default function ChatPanel() {
  const ctx = useChatPage();
  const {
    mainMode, group, members, agentList,
    scrollContainerRef, messagesEndRef, handleScroll, hasMessages,
    showScrollBtns, scrollToTop, scrollToBottom, scrollToPrevMsg, scrollToNextMsg,
    taskChainViews, activeReplyChain, chainsLoading, chainViewCache,
    forceExpandedChainIds,
    handleLoadSubChain,
    isSending, isStreaming, streamingChainId, streamingPacketId, handleStopStream,
    inputText, setInputText, textareaRef,
    chatStreamSend, setIsSending,
  } = ctx;

  // ── @mention autocomplete local state ──
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const mentionDropdownRef = useRef<HTMLDivElement>(null);

  // v2 P2+: 用户从侧边栏点 task 后, useChainViews 会把对应 chainId 加到 forceExpandedChainIds
  // 这里监听这个集合, 滚到对应 chain 头部让用户能立即看到任务过程
  useEffect(() => {
    if (forceExpandedChainIds.size === 0) return;
    const container = scrollContainerRef.current;
    if (!container) return;
    // 用最后一个新加入的 chainId (最近一次点击) 滚到视口
    const lastChainId = Array.from(forceExpandedChainIds).pop();
    if (!lastChainId) return;
    requestAnimationFrame(() => {
      const el = container.querySelector(`[data-chain="${lastChainId}"]`) as HTMLElement | null;
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }, [forceExpandedChainIds, scrollContainerRef]);

  const filteredAgents = useMemo(() => {
    if (mentionQuery === null) return [];
    const q = mentionQuery.toLowerCase();
    return agentList.filter(a => a.name.toLowerCase().includes(q));
  }, [mentionQuery, agentList]);

  // Parse @mention from input text to get agent ID
  function parseMention(text: string): string | undefined {
    const atIdx = text.lastIndexOf('@');
    if (atIdx < 0) return undefined;
    const afterAt = text.slice(atIdx + 1);
    const sorted = [...agentList].sort((a, b) => b.name.length - a.name.length);
    for (const agent of sorted) {
      if (afterAt === agent.name || afterAt.startsWith(agent.name + ' ')) {
        return agent.id;
      }
    }
    return undefined;
  }

  // Detect @mention as user types (for autocomplete dropdown)
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const cursorPos = textarea.selectionStart;
    const textBeforeCursor = inputText.slice(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');
    if (atIndex >= 0) {
      const afterAt = textBeforeCursor.slice(atIndex + 1);
      const charBefore = atIndex > 0 ? textBeforeCursor[atIndex - 1] : ' ';
      if (/\s/.test(charBefore) && !afterAt.includes(' ')) {
        setMentionQuery(afterAt);
        setMentionIndex(0);
        return;
      }
    }
    setMentionQuery(null);
  }, [inputText]);

  // Close mention dropdown on click outside
  useEffect(() => {
    if (mentionQuery === null) return;
    const handler = (e: MouseEvent) => {
      if (mentionDropdownRef.current && !mentionDropdownRef.current.contains(e.target as Node)) {
        setMentionQuery(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [mentionQuery]);

  function selectMention(agent: { id: string; name: string }) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const cursorPos = textarea.selectionStart;
    const textBeforeCursor = inputText.slice(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');
    if (atIndex < 0) return;
    const afterAt = textBeforeCursor.slice(atIndex + 1);
    const newText = inputText.slice(0, atIndex) + '@' + agent.name + ' ' + inputText.slice(atIndex + 1 + afterAt.length);
    setInputText(newText);
    setMentionQuery(null);
    setTimeout(() => {
      textarea.focus();
      const newCursorPos = atIndex + 1 + agent.name.length + 1;
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    }, 0);
  }

  const handleSend = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isSending || isStreaming) return;
    setInputText('');
    setMentionQuery(null);
    const targetAgentId = parseMention(text);
    await chatStreamSend(text, targetAgentId, setIsSending);
  }, [inputText, isSending, isStreaming, setInputText, chatStreamSend, setIsSending, agentList]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionQuery !== null && filteredAgents.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(prev => Math.min(prev + 1, filteredAgents.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(prev => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        selectMention(filteredAgents[mentionIndex]);
        return;
      }
      if (e.key === 'Escape') {
        setMentionQuery(null);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [mentionQuery, filteredAgents, mentionIndex, handleSend]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0 relative">
      {mainMode.startsWith('resource') ? <ResourcePanel /> : (
      <>

      {/* Message stream — Chain Block 模式 */}
      <div ref={scrollContainerRef} onScroll={handleScroll} className="chat-panel-scroll flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {taskChainViews.length === 0 && !activeReplyChain && !chainsLoading ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-12 h-12 bg-foreground/5 flex items-center justify-center">
              <MessageSquareIcon className="w-6 h-6 text-foreground/40" />
            </div>
            <div className="text-center">
              <p className="text-xs font-newspaper-bold text-foreground/80 mb-0.5">群聊: {group.name}</p>
              <p className="text-[10px] text-foreground/30 max-w-48 font-newspaper">
                此群聊有 {(group.tasks || []).length} 个任务，{(group.members || []).length} 个成员
              </p>
              <p className="text-[10px] text-foreground/20 mt-1 font-newspaper">
                发送消息开始与 Agent 对话
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* 顶层链（group chain）— task chain 在主链 packet 位置内联渲染, 不再作为顶层块 */}
            {taskChainViews.map((view) => {
              // Bug1 修复: 不再 filter 掉 activeReplyChain 同 ID 的链。
              // 后端 _get_or_create_chain 在没有活跃 task 时返回已存在的 group chain ID,
              // 前端 activeReplyChain.chain.id 会与 taskChainViews 中的群链 ID 相同,
              // 之前 filter 掉导致历史消息消失。
              // 现在: 如果 activeReplyChain.chain.id === view.chain.id,
              // 把 activeReplyChain 的新 packets (user_pkt + 空 agent_pkt) 追加到 view.packets 末尾,
              // 让 ChainBlock 渲染合并后的视图 (历史 + 新消息), 同时 liveStream=true 显示流式光标。
              // 注意: 不能直接覆盖 view.packets, 否则历史消息会丢失。
              const mergedView = activeReplyChain && activeReplyChain.chain.id === view.chain.id
                ? { ...view, packets: [...view.packets, ...activeReplyChain.packets.filter(p => !view.packets.some(vp => vp.id === p.id))] }
                : view;
              // 默认展开规则（用户可手动覆盖）：
              //   1. group chain: 总是展开（这是用户的主工作面, task chain 在其 packet 位置内联）
              //   2. 顶层 task chain (理论上不会出现, 但兜底): active/pending 展开, 其他折叠
              const isGroupChain = view.chain.chain_type === 'group';
              const isLiveTaskChain = view.chain.chain_type === 'task'
                && (view.chain.status === 'active' || view.chain.status === 'pending');
              // v2 P3+: 当某条 chain 正在被 useChatStream attach 追踪 (resume / 新的流),
              // 也要给 liveStream=true, 这样折叠态下 ChainBlock 的 PacketSummary
              // 会知道这是"流式中"而不是"流式响应中断"
              // Bug1 修复: 如果 activeReplyChain 合并到了本 view, 也标 liveStream=true
              const isLiveStream = (!!streamingChainId && view.chain.id === streamingChainId)
                || (activeReplyChain?.chain.id === view.chain.id);
              return (
                <ChainBlock
                  key={view.chain.id}
                  view={mergedView}
                  defaultExpanded={isGroupChain || isLiveTaskChain}
                  // v2 P2+: 用户从侧边栏点击 task 后, 对应 chain 强制展开一次
                  // ChainBlock 内 useEffect 监听 forceExpanded 变化, 触发 setExpanded(true)
                  forceExpanded={forceExpandedChainIds.has(view.chain.id)}
                  onLoadSubChain={handleLoadSubChain}
                  agentList={agentList}
                  externalSubChainViews={chainViewCache}
                  liveStream={isLiveStream}
                  forceExpandedChainIds={forceExpandedChainIds}
                />
              );
            })}

            {/* 当前活跃的回复链（流式中，默认展开）
                Bug1 修复: 仅当 activeReplyChain.chain.id 不在 taskChainViews 中时才独立渲染。
                如果已存在 (后端返回已存在的 chain_id), 上面的 map 已用 activeReplyChain.packets
                合并渲染, 这里不再重复渲染避免视觉重复。 */}
            {activeReplyChain && !taskChainViews.some(v => v.chain.id === activeReplyChain.chain.id) && (
              <ChainBlock
                key={activeReplyChain.chain.id}
                view={activeReplyChain}
                defaultExpanded
                onLoadSubChain={handleLoadSubChain}
                agentList={agentList}
                externalSubChainViews={chainViewCache}
                liveStream
              />
            )}

            {/* 链数据加载中 */}
            {chainsLoading && (
              <div className="flex items-center justify-center py-4">
                <Loader2Icon className="w-4 h-4 text-foreground/60 animate-spin" />
                <span className="ml-2 text-xs text-foreground/40 font-newspaper">加载链数据…</span>
              </div>
            )}
          </>
        )}

        {/* Typing indicator (only when connecting, not during streaming) */}
        {isSending && !activeReplyChain && (
          <div className="flex gap-1.5">
            <div className="w-6 h-6 bg-foreground/5 flex items-center justify-center flex-shrink-0">
              <BotIcon className="w-3.5 h-3.5 text-foreground/60" />
            </div>
            <div className="flex items-center gap-1.5 px-4 py-2.5 border border-foreground/15">
              <div className="w-1.5 h-1.5 bg-foreground/60 animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-1.5 h-1.5 bg-foreground/60 animate-bounce" style={{ animationDelay: '160ms' }} />
              <div className="w-1.5 h-1.5 bg-foreground/60 animate-bounce" style={{ animationDelay: '320ms' }} />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating scroll buttons */}
      {(hasMessages) && (
        <div className={`absolute right-4 bottom-32 flex flex-col gap-1.5 transition-all duration-300 ${showScrollBtns ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-2 pointer-events-none'}`}>
          <button onClick={scrollToTop} className="w-7 h-7 border border-foreground/20 flex items-center justify-center hover:bg-foreground/5 transition-all duration-200" title="最顶部">
            <ChevronsUpIcon className="w-3.5 h-3.5 text-foreground/40" />
          </button>
          <button onClick={scrollToPrevMsg} className="w-7 h-7 border border-foreground/20 flex items-center justify-center hover:bg-foreground/5 transition-all duration-200" title="上一条">
            <ArrowUpIcon className="w-3.5 h-3.5 text-foreground/40" />
          </button>
          <button onClick={scrollToNextMsg} className="w-7 h-7 border border-foreground/20 flex items-center justify-center hover:bg-foreground/5 transition-all duration-200" title="下一条">
            <ArrowDownIcon className="w-3.5 h-3.5 text-foreground/40" />
          </button>
          <button onClick={scrollToBottom} className="w-7 h-7 border border-foreground/20 flex items-center justify-center hover:bg-foreground/5 transition-all duration-200" title="最底部">
            <ChevronsDownIcon className="w-3.5 h-3.5 text-foreground/40" />
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="flex-shrink-0 px-4 py-2.5 border-t border-foreground/15 relative">
        {/* @mention autocomplete dropdown */}
        {mentionQuery !== null && filteredAgents.length > 0 && (
          <div
            ref={mentionDropdownRef}
            className="absolute bottom-full left-6 right-6 mb-1 border border-foreground/15 overflow-hidden z-50 bg-background"
          >
            <div className="px-3 py-1.5 text-xs text-foreground/40 border-b border-foreground/15 font-newspaper">
              选择 Agent
            </div>
            <div className="max-h-48 overflow-y-auto py-1">
              {filteredAgents.map((agent, idx) => (
                <button
                  key={agent.id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectMention(agent);
                  }}
                  onMouseEnter={() => setMentionIndex(idx)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
                    idx === mentionIndex
                      ? 'bg-foreground/5 text-foreground/80'
                      : 'text-foreground/60 hover:bg-foreground/5'
                  }`}
                >
                  <span className="w-6 h-6 bg-foreground/5 flex items-center justify-center text-xs flex-shrink-0">
                    {getAgentEmoji(agent)}
                  </span>
                  <span className="font-newspaper-bold">{agent.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-end gap-3 border border-foreground/15 px-4 py-3 focus-within:border-foreground/30 transition-all duration-200">
          <textarea
            ref={textareaRef}
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`向 ${group.name} 发送消息… (@名称 指定Agent)`}
            rows={1}
            disabled={isStreaming}
            className="flex-1 bg-transparent text-sm text-foreground/80 placeholder:text-foreground/20 focus:outline-none resize-none leading-relaxed disabled:opacity-50 font-newspaper"
            style={{ minHeight: '22px', maxHeight: '140px', overflowY: 'auto' }}
          />
          {isStreaming ? (
            <button
              onClick={handleStopStream}
              className="flex-shrink-0 w-8 h-8 border border-foreground/30 flex items-center justify-center hover:bg-foreground/5 transition-opacity"
              title="停止生成"
            >
              <StopCircleIcon className="w-3.5 h-3.5 text-foreground/60" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!inputText.trim() || isSending}
              className="flex-shrink-0 w-8 h-8 border border-foreground/30 flex items-center justify-center hover:bg-foreground/5 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <SendIcon className="w-3.5 h-3.5 text-foreground/60" />
            </button>
          )}
        </div>

        {/* Participant avatars */}
        <div className="flex items-center gap-1.5 mt-2 px-1">
          {members.map(member => (
            <span
              key={member.id}
              className="w-5 h-5 text-xs flex items-center justify-center bg-foreground/5 select-none"
            >
              {getAgentEmoji(member.agent)}
            </span>
          ))}
          {members.length > 0 && (
            <span className="text-xs text-foreground/30 ml-1 font-newspaper">
              {members.length} 个 Agent 参与中
            </span>
          )}
        </div>
      </div>
      </>
      )}
    </div>
  );
}
