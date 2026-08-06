import { useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ChevronDownIcon, Maximize2Icon, XIcon, WrenchIcon,
} from 'lucide-react';
import RenderEngine from '../../render-engine/RenderEngine';
import type { RenderSpec } from '../../render-engine/types';

export interface ToolCallInfo {
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  tool_call_id?: string;
  timestamp?: string;
}

export interface ContentSegment {
  type: 'text' | 'think' | 'tool_call_pos';
  content: string;
  complete: boolean;
  toolCalls?: ToolCallInfo[];
}

export function getAgentEmoji(agent?: { id?: string; avatar?: string | null } | null): string {
  if (!agent) return '🤖';
  if (agent.avatar && agent.avatar.length <= 4 && !agent.avatar.includes('?')) return agent.avatar;
  // v2 P3: 删除 role 字段, agent 的头像统一用 avatar 字段
  return '🤖';
}

const THINK_OPEN_TAG = '<' + 'think>';
const THINK_CLOSE_TAG = '</' + 'think>';
const THINK_OPEN_RE = /<think\s*>/gi;
const THINK_BLOCK_RE = /<think\s*>([\s\S]*?)<\/think\s*>/gi;

export function parseThinkContent(raw: string): ContentSegment[] {
  let cleaned = raw
    .replace(/\[TOOL_CALL\][\s\S]*?\[\/TOOL_CALL\]/gi, '')
    .replace(/\[Tool Call\].*/gi, '')
    .replace(/\[Tool Result\].*/gi, '')
    .replace(/\[Tool Error\].*/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  // 清理部分 [TOOL_CAL 标记（流式场景，LLM 正在生成标记但还没闭合）
  const partialToolIdx = cleaned.lastIndexOf('[TOOL_CAL');
  if (partialToolIdx >= 0) {
    const after = cleaned.slice(partialToolIdx);
    if (!after.includes('[/TOOL_CALL]')) {
      cleaned = cleaned.slice(0, partialToolIdx).trim();
    }
  }

  const segments: ContentSegment[] = [];

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  THINK_BLOCK_RE.lastIndex = 0;
  while ((match = THINK_BLOCK_RE.exec(cleaned)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', content: cleaned.slice(lastIndex, match.index), complete: true });
    }
    segments.push({ type: 'think', content: match[1], complete: true });
    lastIndex = THINK_BLOCK_RE.lastIndex;
  }

  if (lastIndex < cleaned.length) {
    const remaining = cleaned.slice(lastIndex);
    THINK_OPEN_RE.lastIndex = 0;
    const openMatch = THINK_OPEN_RE.exec(remaining);
    if (openMatch) {
      if (openMatch.index > 0) {
        segments.push({ type: 'text', content: remaining.slice(0, openMatch.index), complete: true });
      }
      const thinkContent = remaining.slice(openMatch.index + openMatch[0].length);
      segments.push({ type: 'think', content: thinkContent, complete: false });
    } else {
      const partialIdx = remaining.lastIndexOf('<');
      if (partialIdx >= 0) {
        const afterLt = remaining.slice(partialIdx).toLowerCase();
        const fullOpenTag = THINK_OPEN_TAG.toLowerCase();
        let isPartialThink = false;
        if (afterLt.length < fullOpenTag.length) {
          isPartialThink = fullOpenTag.startsWith(afterLt);
        }
        if (isPartialThink) {
          if (partialIdx > 0) {
            segments.push({ type: 'text', content: remaining.slice(0, partialIdx), complete: true });
          }
          segments.push({ type: 'think', content: '', complete: false });
        } else {
          segments.push({ type: 'text', content: remaining, complete: true });
        }
      } else {
        segments.push({ type: 'text', content: remaining, complete: true });
      }
    }
  }

  const finalSegments = segments.map(seg => {
    if (seg.type === 'text') {
      const cleanText = seg.content
        .replace(/<think\s*>[\s\S]*?<\/think\s*>/gi, '')
        .replace(/<think\s*>/gi, '')
        .replace(/<\/think\s*>/gi, '')
        .replace(/<\/?thi[^>]*>?/gi, '')
        .replace(/\(think\)!/gi, '')
        .trim();
      return { ...seg, content: cleanText };
    }
    return seg;
  }).filter(seg => !(seg.type === 'text' && !seg.content.trim()));

  // 把 text segment 里的 <tool_call_pos /> 标记拆成独立 segment,
  // 让前端能按原始时序穿插渲染工具调用 (而非统一堆到消息末尾).
  // on_token 一次性推送完整标记, 一般不会有部分标记; 但流式网络传输
  // 理论上可能拆包, 这里对部分标记做兜底 (当作 incomplete text 保留, 等闭合).
  return splitToolCallPos(finalSegments);
}

const TOOL_CALL_POS_RE = /<tool_call_pos\s*\/>/gi;
const TOOL_CALL_POS_PARTIAL_RE = /<tool_call_pos[^>]*$/i;

function splitToolCallPos(segments: ContentSegment[]): ContentSegment[] {
  const result: ContentSegment[] = [];
  for (const seg of segments) {
    if (seg.type !== 'text') {
      result.push(seg);
      continue;
    }
    let text = seg.content;
    // 先把尾部不完整的 <tool_call_pos 标记拆出来 (流式场景), 当作 incomplete text 保留
    let partialTail = '';
    const partialMatch = text.match(TOOL_CALL_POS_PARTIAL_RE);
    if (partialMatch && partialMatch.index !== undefined) {
      partialTail = partialMatch[0];
      text = text.slice(0, partialMatch.index);
    }

    let lastIndex = 0;
    let match: RegExpExecArray | null;
    TOOL_CALL_POS_RE.lastIndex = 0;
    while ((match = TOOL_CALL_POS_RE.exec(text)) !== null) {
      if (match.index > lastIndex) {
        result.push({ type: 'text', content: text.slice(lastIndex, match.index), complete: true });
      }
      result.push({ type: 'tool_call_pos', content: '', complete: true });
      lastIndex = TOOL_CALL_POS_RE.lastIndex;
    }
    if (lastIndex < text.length) {
      result.push({ type: 'text', content: text.slice(lastIndex), complete: seg.complete });
    }
    if (partialTail) {
      result.push({ type: 'text', content: partialTail, complete: false });
    }
  }
  return result.filter(s => !(s.type === 'text' && !s.content.trim()));
}

export function ToolCallRenderer({ toolCalls }: { toolCalls: ToolCallInfo[] }) {
  return (
    <div className="space-y-1 mt-1">
      {toolCalls.map((call, i) => {
        const args = call.arguments || {};
        const argsStr = Object.keys(args).length > 0
          ? Object.entries(args).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')
          : '';
        const resultStr = call.result != null
          ? (typeof call.result === 'string' ? call.result : JSON.stringify(call.result, null, 2))
          : null;
        return (
          <details key={call.tool_call_id || `tc-${i}`} className="my-1 w-fit max-w-full rounded-lg border border-foreground/15 bg-foreground/[0.02] group overflow-hidden" style={{ maxWidth: 'min(100%, 560px)' }}>
            <summary className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-foreground/60 cursor-pointer select-none hover:text-foreground/80 transition-colors">
              <WrenchIcon className="w-3 h-3" />
              <span className="font-medium">{call.tool_name}</span>
              {argsStr && <span className="text-foreground/40 ml-1 truncate max-w-[200px]">({argsStr})</span>}
              <ChevronDownIcon className="w-3 h-3 ml-auto transition-transform group-open:rotate-180 flex-shrink-0" />
            </summary>
            <div className="px-2.5 pb-1.5 border-t border-foreground/10 pt-1.5 space-y-1">
              {resultStr && (
                <div className="text-xs text-foreground/70 border border-foreground/10 p-1.5 whitespace-pre-wrap max-h-64 overflow-y-auto font-newspaper">
                  <div className="font-medium text-foreground/50 mb-0.5">返回结果</div>
                  {resultStr.length > 2000 ? resultStr.substring(0, 2000) + '…' : resultStr}
                </div>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}

export function DataViewExpandButton({ spec }: { spec: RenderSpec }) {
  const [open, setOpen] = useState(false);
  const popupSpec = { ...spec, style: { ...spec.style, height: '100%', popup: true } };
  return (
    <>
      <button
        onClick={(e) => { e.preventDefault(); setOpen(true); }}
        className="ml-auto p-0.5 rounded text-muted-foreground/50 hover:text-primary hover:bg-primary/10 transition-colors"
        title="弹出查看"
      >
        <Maximize2Icon className="w-3 h-3" />
      </button>
      {open && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <div className="relative w-[85vw] h-[85vh] bg-background rounded-xl shadow-2xl border overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
              <h2 className="text-sm font-semibold">{spec.title || spec.view_type}</h2>
              <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-accent transition-colors">
                <XIcon className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <RenderEngine spec={popupSpec} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
