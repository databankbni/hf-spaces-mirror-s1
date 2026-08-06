import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

export interface MarkdownHeading {
  id: string;
  text: string;
  level: number;
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
  compact?: boolean;
}

function slugifyHeading(text: string) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-') || 'section';
}

export function extractMarkdownHeadings(content: string): MarkdownHeading[] {
  const seen = new Map<string, number>();
  const headings: MarkdownHeading[] = [];

  content.split('\n').forEach(line => {
    const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
    if (!match) return;

    const text = match[2].replace(/[#*_`~\[\]()]/g, '').trim();
    if (!text) return;

    const baseId = slugifyHeading(text);
    const count = seen.get(baseId) || 0;
    seen.set(baseId, count + 1);
    headings.push({
      id: count ? `${baseId}-${count + 1}` : baseId,
      text,
      level: match[1].length,
    });
  });

  return headings;
}

function buildComponents(compact: boolean): Components {
  const headingClasses = compact
    ? {
        h1: 'text-base font-bold mt-3 mb-1.5',
        h2: 'text-sm font-bold mt-2.5 mb-1',
        h3: 'text-sm font-semibold mt-2 mb-1',
      }
    : {
        h1: 'text-2xl font-bold mt-8 mb-4 first:mt-0 tracking-tight',
        h2: 'text-xl font-semibold mt-7 mb-3 border-b border-border pb-2',
        h3: 'text-lg font-semibold mt-5 mb-2',
      };

  return {
    h1: ({ children }) => <h1 id={slugifyHeading(String(children))} className={headingClasses.h1}>{children}</h1>,
    h2: ({ children }) => <h2 id={slugifyHeading(String(children))} className={headingClasses.h2}>{children}</h2>,
    h3: ({ children }) => <h3 id={slugifyHeading(String(children))} className={headingClasses.h3}>{children}</h3>,
    h4: ({ children }) => <h4 className={compact ? 'text-sm font-semibold mt-2 mb-1' : 'text-base font-semibold mt-4 mb-2'}>{children}</h4>,
    p: ({ children }) => <p className={compact ? 'mb-2 last:mb-0 leading-relaxed' : 'mb-4 last:mb-0 leading-7'}>{children}</p>,
    ul: ({ children }) => <ul className={compact ? 'list-disc pl-5 mb-2 space-y-1' : 'list-disc pl-6 mb-4 space-y-1.5'}>{children}</ul>,
    ol: ({ children }) => <ol className={compact ? 'list-decimal pl-5 mb-2 space-y-1' : 'list-decimal pl-6 mb-4 space-y-1.5'}>{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    code: ({ className, children, ...props }) => {
      const isBlock = className?.includes('language-');
      if (isBlock) {
        return (
          <pre className="my-4 overflow-x-auto rounded-xl border border-border bg-muted/50 px-4 py-3">
            <code className="text-xs leading-relaxed" {...props}>{children}</code>
          </pre>
        );
      }
      return <code className="rounded-md bg-muted px-1.5 py-0.5 text-[0.88em]" {...props}>{children}</code>;
    },
    pre: ({ children }) => <>{children}</>,
    blockquote: ({ children }) => (
      <blockquote className="my-4 border-l-4 border-primary/40 bg-primary/5 px-4 py-3 text-muted-foreground">
        {children}
      </blockquote>
    ),
    table: ({ children }) => (
      <div className="my-4 overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border-b border-r border-border bg-muted/60 px-3 py-2 text-left font-semibold last:border-r-0">{children}</th>,
    td: ({ children }) => <td className="border-b border-r border-border px-3 py-2 align-top last:border-r-0">{children}</td>,
    hr: () => <hr className="my-6 border-border" />,
    a: ({ href, children }) => {
      const isExternal = href ? /^[a-z][a-z0-9+.-]*:/i.test(href) : false;
      return (
        <a
          href={href}
          target={isExternal ? '_blank' : undefined}
          rel={isExternal ? 'noopener noreferrer' : undefined}
          className="text-primary underline underline-offset-4 hover:opacity-80"
        >
          {children}
        </a>
      );
    },
  };
}

export default function MarkdownRenderer({ content, className, compact = false }: MarkdownRendererProps) {
  return (
    <div className={cn('text-foreground', compact ? 'text-xs' : 'text-sm', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(compact)}>
        {content || ''}
      </ReactMarkdown>
    </div>
  );
}
