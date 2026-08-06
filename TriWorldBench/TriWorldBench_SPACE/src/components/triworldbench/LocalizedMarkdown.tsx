import React from "react";
import { contentValue, type LocalizedText } from "@/lib/i18n";

type InlineToken = {
  kind: "strong" | "em" | "code" | "link" | "text";
  value: string;
  href?: string;
};

function isSafeHref(value: string): boolean {
  return /^(https?:\/\/|mailto:|\/|#)/i.test(value.trim());
}

function tokenizeInline(value: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  const expression = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\)|\*[^*]+\*)/g;
  let cursor = 0;
  for (const match of value.matchAll(expression)) {
    const index = match.index ?? 0;
    if (index > cursor) tokens.push({ kind: "text", value: value.slice(cursor, index) });
    const token = match[0];
    if (token.startsWith("**")) tokens.push({ kind: "strong", value: token.slice(2, -2) });
    else if (token.startsWith("`")) tokens.push({ kind: "code", value: token.slice(1, -1) });
    else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(token);
      if (link && isSafeHref(link[2])) tokens.push({ kind: "link", value: link[1], href: link[2] });
      else tokens.push({ kind: "text", value: token });
    } else tokens.push({ kind: "em", value: token.slice(1, -1) });
    cursor = index + token.length;
  }
  if (cursor < value.length) tokens.push({ kind: "text", value: value.slice(cursor) });
  return tokens;
}

export function MarkdownInline({ value }: { value: string }) {
  const lines = value.split("\n");
  return (
    <>
      {lines.map((line, lineIndex) => (
        <React.Fragment key={`${lineIndex}-${line}`}>
          {lineIndex ? <br /> : null}
          {tokenizeInline(line).map((token, index) => {
            if (token.kind === "strong") return <strong key={index}><MarkdownInline value={token.value} /></strong>;
            if (token.kind === "em") return <em key={index}><MarkdownInline value={token.value} /></em>;
            if (token.kind === "code") return <code key={index}>{token.value}</code>;
            if (token.kind === "link") {
              const external = /^https?:\/\//i.test(token.href || "");
              return <a href={token.href} key={index} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>{token.value}</a>;
            }
            return <React.Fragment key={index}>{token.value}</React.Fragment>;
          })}
        </React.Fragment>
      ))}
    </>
  );
}

export function MarkdownBlocks({ value }: { value: string }) {
  const lines = value.replace(/\r\n?/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(<pre className="twb-markdown-code" key={`code-${blocks.length}`}><code data-language={language || undefined}>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = Math.min(5, heading[1].length + 2);
      const Tag = `h${level}` as "h3" | "h4" | "h5";
      blocks.push(<Tag key={`heading-${blocks.length}`}><MarkdownInline value={heading[2]} /></Tag>);
      index += 1;
      continue;
    }
    const unordered = /^[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const orderedList = Boolean(ordered);
      const values: string[] = [];
      while (index < lines.length) {
        const match = orderedList ? /^\d+[.)]\s+(.+)$/.exec(lines[index]) : /^[-*+]\s+(.+)$/.exec(lines[index]);
        if (!match) break;
        values.push(match[1]);
        index += 1;
      }
      const List = orderedList ? "ol" : "ul";
      blocks.push(<List key={`list-${blocks.length}`}>{values.map((item, itemIndex) => <li key={itemIndex}><MarkdownInline value={item} /></li>)}</List>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !/^[-*+]\s+/.test(lines[index]) &&
      !/^\d+[.)]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(<p key={`paragraph-${blocks.length}`}><MarkdownInline value={paragraph.join("\n")} /></p>);
  }

  return <>{blocks}</>;
}

export function LocalizedMarkdown({
  text,
  inline = false,
}: {
  text?: LocalizedText;
  inline?: boolean;
}) {
  const en = contentValue(text?.en);
  const zh = contentValue(text?.zh);
  if (!en && !zh) return null;
  if (inline) {
    return (
      <>
        {en ? <span className="i18n-en"><MarkdownInline value={en} /></span> : null}
        {zh ? <span className="i18n-zh"><MarkdownInline value={zh} /></span> : null}
      </>
    );
  }
  return (
    <>
      {en ? <div className="twb-markdown i18n-en"><MarkdownBlocks value={en} /></div> : null}
      {zh ? <div className="twb-markdown i18n-zh"><MarkdownBlocks value={zh} /></div> : null}
    </>
  );
}
