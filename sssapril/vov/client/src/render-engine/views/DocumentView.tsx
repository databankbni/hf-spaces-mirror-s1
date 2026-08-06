import type { ViewComponentProps } from '../types';
import MarkdownRenderer from '../../components/markdown/MarkdownRenderer';
import { extractMarkdownHeadings } from '../../components/markdown/MarkdownRenderer';
import { useMemo } from 'react';

export default function DocumentView({ data, options }: ViewComponentProps) {
  const content = extractContent(data, options?.content_field);
  const compact = options?.compact ?? false;
  const showToc = options?.show_toc ?? false;

  const headings = useMemo(() => {
    if (!showToc || !content) return [];
    return extractMarkdownHeadings(content);
  }, [showToc, content]);

  if (!content) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无内容'}</div>;
  }

  return (
    <div className="flex gap-6">
      {showToc && headings.length > 0 && (
        <nav className="hidden lg:block w-52 flex-shrink-0">
          <div className="sticky top-6 rounded-xl border border-border bg-card p-3">
            <div className="text-xs font-semibold text-muted-foreground mb-2">目录</div>
            <div className="flex flex-col gap-1">
              {headings.map(h => (
                <a
                  key={h.id}
                  href={`#${h.id}`}
                  className={`text-xs text-muted-foreground hover:text-primary transition-colors truncate ${h.level === 1 ? 'font-medium' : h.level === 2 ? 'pl-3' : 'pl-6'}`}
                >
                  {h.text}
                </a>
              ))}
            </div>
          </div>
        </nav>
      )}
      <div className="flex-1 min-w-0">
        <MarkdownRenderer content={content} compact={compact} />
      </div>
    </div>
  );
}

function extractContent(data: unknown, contentField?: string): string | null {
  if (typeof data === 'string') return data;
  if (!data || typeof data !== 'object') return null;

  const obj = data as Record<string, unknown>;
  const field = contentField || 'content';

  if (typeof obj[field] === 'string') return obj[field] as string;

  // 尝试常见字段名
  for (const key of ['content', 'body', 'text', 'markdown', 'html']) {
    if (typeof obj[key] === 'string') return obj[key] as string;
  }

  // 如果整个对象就是内容（没有 content 字段），尝试 JSON 序列化
  return JSON.stringify(data, null, 2);
}
