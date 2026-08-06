import { zipSync, strToU8 } from 'fflate';

/**
 * Response export + artifact sharing.
 *
 * Downloads (Markdown / HTML / plain text / ZIP) are produced entirely in the
 * browser — no network, no server. Only `shareArtifact` uploads, and it does so
 * via the `/api/blob-upload` serverless route (the client never holds the Blob
 * token). All returned Share URLs are public.
 */

const UPLOAD_ENDPOINT = '/api/blob-upload';


/**
 * Record a locally-produced export in the Artifacts Library. Fire-and-forget by design: a
 * download has already happened by the time this runs, so a library failure must stay silent.
 */
function noteExport(type: string, title: string, mimeType: string, sizeBytes: number): void {
    void import('./fabric')
        .then((m) => m.recordLocalArtifact({ type, title, mimeType, sizeBytes }))
        .catch(() => undefined);
}

// ─── Public API ───────────────────────────────────────────────────────────

/** Download the raw Markdown response as a `.md` file. */
export function exportResponseAsMarkdown(content: string, title?: string): void {
    const resolved = resolveTitle(content, title);
    triggerDownload(`${slugify(resolved)}.md`, content, 'text/markdown;charset=utf-8');
    noteExport('document', resolved, 'text/markdown', content.length);
}

/** Download a clean, standalone, THOX-themed HTML document of the response. */
export function exportResponseAsHtml(content: string, title?: string): void {
    const resolved = resolveTitle(content, title);
    const slug = slugify(resolved);
    const html = buildStandaloneHtml(resolved, markdownToHtml(content));
    triggerDownload(`${slug}.html`, html, 'text/html;charset=utf-8');
    noteExport('document', resolved, 'text/html', html.length);
}

/** Download a `.zip` bundling the Markdown, standalone HTML, and plain-text forms. */
export function exportAsZip(content: string, title?: string): void {
    const resolved = resolveTitle(content, title);
    const slug = slugify(resolved);
    const html = buildStandaloneHtml(resolved, markdownToHtml(content));

    const files: Record<string, Uint8Array> = {};
    files[`${slug}.md`] = strToU8(content);
    files[`${slug}.html`] = strToU8(html);
    files[`${slug}.txt`] = strToU8(toPlainText(content));

    const zipped = zipSync(files, { level: 6 });
    triggerDownload(`${slug}.zip`, zipped, 'application/zip');
    noteExport('bundle', resolved, 'application/zip', zipped.length);
}

/**
 * Build the shareable HTML for a response:
 *  - if the response embeds a runnable HTML artifact (an ```html block or a full
 *    document), that runnable page is published;
 *  - otherwise a themed, standalone rendering of the response is published.
 */
export function buildShareableHtml(content: string, title?: string): string {
    const resolved = resolveTitle(content, title);
    const runnable = extractRunnableHtml(content);
    if (runnable) return wrapRunnableHtml(runnable, resolved);
    return buildStandaloneHtml(resolved, markdownToHtml(content));
}

/**
 * Upload an HTML document to Vercel Blob via the serverless route and return its
 * public URL. This is the ONLY function here that performs a network request.
 */
export async function shareArtifact(html: string, filename = 'artifact.html'): Promise<string> {
    const res = await fetch(UPLOAD_ENDPOINT, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
            filename,
            contentType: 'text/html; charset=utf-8',
            text: html,
        }),
    });

    if (!res.ok) {
        let message = `Upload failed (${res.status}).`;
        try {
            const data = await res.json();
            if (data && typeof data.error === 'string') message = data.error;
        } catch {
            /* keep default message */
        }
        throw new Error(message);
    }

    const data = (await res.json()) as { url?: string };
    if (!data.url) throw new Error('Upload succeeded but no URL was returned.');
    return data.url;
}

/**
 * Convenience: build the shareable HTML and upload it in one call.
 *
 * Every successful share is also recorded in the Artifacts Library (CX Fabric `Artifact` shape).
 * Recording is best-effort: a library write must never fail a share the user already completed.
 */
export async function shareResponseAsArtifact(
    content: string,
    title?: string,
    conversationId?: string
): Promise<string> {
    const resolved = resolveTitle(content, title);
    const html = buildShareableHtml(content, resolved);
    const url = await shareArtifact(html, `${slugify(resolved)}.html`);
    try {
        const { recordLocalArtifact } = await import('./fabric');
        await recordLocalArtifact({
            type: 'web_app',
            title: resolved,
            ref: url,
            conversationId,
            mimeType: 'text/html',
            sizeBytes: html.length,
        });
    } catch {
        /* library write is best-effort */
    }
    return url;
}

// ─── Title / filename helpers ──────────────────────────────────────────────

export function resolveTitle(content: string, title?: string): string {
    if (title && title.trim()) return title.trim().slice(0, 80);
    const firstLine = content
        .split('\n')
        .map((l) =>
            l
                .replace(/^#{1,6}\s*/, '')
                .replace(/[*_`>#[\]()]/g, '')
                .trim(),
        )
        .find((l) => l.length > 0);
    return (firstLine || 'ThoxOS Response').slice(0, 80);
}

function slugify(title: string): string {
    const base = title
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60);
    return base || 'thoxos-response';
}

// ─── Download helper ───────────────────────────────────────────────────────

function triggerDownload(filename: string, data: string | Uint8Array, mime: string): void {
    // Wrap bytes in a fresh ArrayBuffer-backed view so TS accepts it as BlobPart
    // (fflate's Uint8Array can be SharedArrayBuffer-typed under strict lib.dom).
    const part: BlobPart = typeof data === 'string' ? data : new Uint8Array(data);
    const blob = new Blob([part], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ─── Runnable-artifact extraction ──────────────────────────────────────────

/** Pull a runnable HTML artifact out of a response, if one is present. */
export function extractRunnableHtml(markdown: string): string | null {
    const fenced = markdown.match(/```html\s*\n([\s\S]*?)```/i);
    if (fenced && fenced[1].trim()) return fenced[1].trim();
    if (/<!doctype html>/i.test(markdown) || /<html[\s>]/i.test(markdown)) {
        return markdown.trim();
    }
    return null;
}

/** Ensure an artifact is a complete, standalone document that a browser can run. */
function wrapRunnableHtml(html: string, title: string): string {
    if (/<html[\s>]/i.test(html) || /<!doctype html>/i.test(html)) return html;
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}</title>
</head>
<body>
${html}
</body>
</html>`;
}

// ─── Standalone themed document ────────────────────────────────────────────

function buildStandaloneHtml(title: string, bodyHtml: string): string {
    const safeTitle = escapeHtml(title);
    const year = new Date().getFullYear();
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${safeTitle}</title>
<style>
:root {
  --bg: #0a0a0f;
  --surface: #12121a;
  --surface-2: #1a1a26;
  --border: rgba(255,255,255,0.08);
  --text: #e8e8ed;
  --text-2: #8888a0;
  --text-3: #555570;
  --accent: #10b981;
  --accent-2: #34d399;
  --radius: 12px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 760px; margin: 0 auto; padding: 56px 24px 96px; }
.masthead { display: flex; align-items: center; gap: 10px; margin-bottom: 32px; color: var(--text-2); font-size: 13px; }
.brand-dot { width: 22px; height: 22px; border-radius: 7px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); box-shadow: 0 0 18px rgba(16,185,129,0.35); }
.brand { color: var(--text); font-weight: 600; letter-spacing: -0.01em; }
h1, h2, h3, h4 { color: var(--text); font-weight: 650; letter-spacing: -0.02em; line-height: 1.3; margin: 1.6em 0 0.6em; }
h1 { font-size: 30px; margin-top: 0; }
h2 { font-size: 23px; }
h3 { font-size: 19px; }
h4 { font-size: 16px; }
p { margin: 0 0 1em; color: var(--text); }
a { color: var(--accent-2); text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: #fff; font-weight: 650; }
em { color: var(--text); }
del { color: var(--text-3); }
ul, ol { padding-left: 1.4em; margin: 0 0 1em; }
li { margin: 0.3em 0; }
code {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.86em;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0.12em 0.4em;
}
pre.code {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  overflow-x: auto;
  margin: 1.2em 0;
}
pre.code code { background: none; border: none; padding: 0; font-size: 13px; line-height: 1.6; color: var(--text); }
blockquote {
  margin: 1.2em 0;
  padding: 12px 16px;
  border-left: 3px solid var(--accent);
  background: rgba(16,185,129,0.06);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-2);
}
hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
table { width: 100%; border-collapse: collapse; margin: 1.2em 0; font-size: 14px; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
th { background: var(--surface-2); color: var(--text); font-weight: 600; }
td { color: var(--text-2); }
img { max-width: 100%; border-radius: var(--radius); }
.footer { margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--text-3); font-size: 12px; }
</style>
</head>
<body>
<main class="wrap">
  <div class="masthead">
    <span class="brand-dot"></span>
    <span class="brand">ThoxOS</span>
    <span>· Web Edition</span>
  </div>
  <article>
${bodyHtml}
  </article>
  <div class="footer">Exported from ThoxOS Web Edition · ${year}</div>
</main>
</body>
</html>`;
}

// ─── Minimal Markdown → HTML converter ─────────────────────────────────────
// Covers headings, emphasis, inline code, links/images, fenced code, blockquotes,
// lists, GFM tables, and horizontal rules. All text is HTML-escaped.

function markdownToHtml(md: string): string {
    const lines = md.replace(/\r\n/g, '\n').split('\n');
    const out: string[] = [];
    let i = 0;
    let listMode: 'ul' | 'ol' | null = null;

    const closeList = () => {
        if (listMode) {
            out.push(`</${listMode}>`);
            listMode = null;
        }
    };

    while (i < lines.length) {
        const line = lines[i];

        // Fenced code block
        const fence = line.match(/^```\s*([\w-]*)\s*$/);
        if (fence) {
            closeList();
            const lang = fence[1] || '';
            const buf: string[] = [];
            i++;
            while (i < lines.length && !/^```\s*$/.test(lines[i])) {
                buf.push(lines[i]);
                i++;
            }
            i++; // consume closing fence (if present)
            const langAttr = lang ? ` data-lang="${escapeAttr(lang)}"` : '';
            out.push(`<pre class="code"><code${langAttr}>${escapeHtml(buf.join('\n'))}</code></pre>`);
            continue;
        }

        // Blank line
        if (line.trim() === '') {
            closeList();
            i++;
            continue;
        }

        // Heading
        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            closeList();
            const level = heading[1].length;
            out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
            i++;
            continue;
        }

        // Horizontal rule
        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
            closeList();
            out.push('<hr />');
            i++;
            continue;
        }

        // Blockquote
        if (/^\s*>\s?/.test(line)) {
            closeList();
            const buf: string[] = [];
            while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
                buf.push(lines[i].replace(/^\s*>\s?/, ''));
                i++;
            }
            out.push(`<blockquote>${renderInline(buf.join(' '))}</blockquote>`);
            continue;
        }

        // GFM table (header row + delimiter row)
        if (
            line.includes('|') &&
            i + 1 < lines.length &&
            lines[i + 1].includes('-') &&
            /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])
        ) {
            closeList();
            const header = splitTableRow(line);
            i += 2; // header + delimiter
            const rows: string[][] = [];
            while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
                rows.push(splitTableRow(lines[i]));
                i++;
            }
            let table = '<table><thead><tr>';
            table += header.map((c) => `<th>${renderInline(c)}</th>`).join('');
            table += '</tr></thead><tbody>';
            for (const row of rows) {
                table += '<tr>' + row.map((c) => `<td>${renderInline(c)}</td>`).join('') + '</tr>';
            }
            table += '</tbody></table>';
            out.push(table);
            continue;
        }

        // Unordered list
        const ul = line.match(/^\s*[-*+]\s+(.*)$/);
        if (ul) {
            if (listMode !== 'ul') {
                closeList();
                out.push('<ul>');
                listMode = 'ul';
            }
            out.push(`<li>${renderInline(ul[1])}</li>`);
            i++;
            continue;
        }

        // Ordered list
        const ol = line.match(/^\s*\d+\.\s+(.*)$/);
        if (ol) {
            if (listMode !== 'ol') {
                closeList();
                out.push('<ol>');
                listMode = 'ol';
            }
            out.push(`<li>${renderInline(ol[1])}</li>`);
            i++;
            continue;
        }

        // Paragraph — gather until a blank line or the start of another block
        closeList();
        const buf: string[] = [line];
        i++;
        while (i < lines.length && lines[i].trim() !== '' && !isBlockStart(lines[i])) {
            buf.push(lines[i]);
            i++;
        }
        out.push(`<p>${renderInline(buf.join(' '))}</p>`);
    }

    closeList();
    return out.join('\n');
}

function isBlockStart(line: string): boolean {
    return (
        /^```/.test(line) ||
        /^#{1,6}\s+/.test(line) ||
        /^\s*>\s?/.test(line) ||
        /^\s*[-*+]\s+/.test(line) ||
        /^\s*\d+\.\s+/.test(line) ||
        /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
    );
}

function splitTableRow(line: string): string[] {
    return line
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((c) => c.trim());
}

/** Inline formatting. Links/images/code are stashed before escaping to keep URLs intact. */
function renderInline(input: string): string {
    const tokens: string[] = [];
    const stash = (html: string): string => {
        tokens.push(html);
        return `${tokens.length - 1}`;
    };

    let s = input;
    // Images
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, (_m, alt: string, url: string) =>
        stash(`<img src="${escapeAttr(url)}" alt="${escapeAttr(alt)}" />`),
    );
    // Links
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, (_m, text: string, url: string) =>
        stash(
            `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>`,
        ),
    );
    // Inline code
    s = s.replace(/`([^`]+)`/g, (_m, code: string) => stash(`<code>${escapeHtml(code)}</code>`));

    // Escape everything that remains, then apply emphasis on the safe text.
    let t = escapeHtml(s);
    t = t
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/~~([^~]+)~~/g, '<del>$1</del>');

    // Restore stashed tokens.
    t = t.replace(/(\d+)/g, (_m, n: string) => tokens[Number(n)]);
    return t;
}

// ─── Plain text ────────────────────────────────────────────────────────────

function toPlainText(md: string): string {
    return md
        .replace(/```(\w*)\n?/g, '')
        .replace(/```/g, '')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/__([^_]+)__/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/~~([^~]+)~~/g, '$1')
        .replace(/^\s*>\s?/gm, '')
        .replace(/^\s*[-*+]\s+/gm, '• ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

// ─── Escaping ──────────────────────────────────────────────────────────────

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeAttr(s: string): string {
    return escapeHtml(s);
}
