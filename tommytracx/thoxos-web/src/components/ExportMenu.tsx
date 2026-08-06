import { useState, useRef, useEffect, useCallback } from 'react';
import {
    Share2,
    Copy,
    Check,
    FileText,
    FileCode,
    Archive,
    Globe,
    Loader2,
    Link as LinkIcon,
    X,
    AlertCircle,
} from 'lucide-react';
import {
    exportResponseAsMarkdown,
    exportResponseAsHtml,
    exportAsZip,
    buildShareableHtml,
    shareArtifact,
    resolveTitle,
} from '../lib/blobExport';

interface ExportMenuProps {
    /** The assistant response content (Markdown). */
    content: string;
    /** Optional explicit title; derived from the content when omitted. */
    title?: string;
}

type ShareState =
    | { status: 'idle' }
    | { status: 'sharing' }
    | { status: 'done'; url: string }
    | { status: 'error'; message: string };

export default function ExportMenu({ content, title }: ExportMenuProps) {
    const [open, setOpen] = useState(false);
    const [copiedMd, setCopiedMd] = useState(false);
    const [copiedLink, setCopiedLink] = useState(false);
    const [share, setShare] = useState<ShareState>({ status: 'idle' });
    const containerRef = useRef<HTMLDivElement>(null);

    const responseTitle = resolveTitle(content, title);

    // Close on outside click / Escape
    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setOpen(false);
            }
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);

    const handleCopyMarkdown = useCallback(async () => {
        await navigator.clipboard.writeText(content);
        setCopiedMd(true);
        setTimeout(() => setCopiedMd(false), 2000);
    }, [content]);

    const handleShare = useCallback(async () => {
        setShare({ status: 'sharing' });
        try {
            const html = buildShareableHtml(content, responseTitle);
            const slug =
                responseTitle
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-')
                    .replace(/^-+|-+$/g, '')
                    .slice(0, 60) || 'thoxos-response';
            const url = await shareArtifact(html, `${slug}.html`);
            setShare({ status: 'done', url });
        } catch (err) {
            setShare({
                status: 'error',
                message: err instanceof Error ? err.message : 'Something went wrong while sharing.',
            });
        }
    }, [content, responseTitle]);

    const handleCopyLink = useCallback(async () => {
        if (share.status !== 'done') return;
        await navigator.clipboard.writeText(share.url);
        setCopiedLink(true);
        setTimeout(() => setCopiedLink(false), 2000);
    }, [share]);

    const itemClass =
        'w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-text-secondary hover:text-text-primary hover:bg-bg-surface-hover transition-colors text-left';

    return (
        <div className="relative" ref={containerRef}>
            <button
                onClick={() => setOpen((v) => !v)}
                className={`p-1.5 rounded-md transition-colors ${
                    open
                        ? 'text-accent bg-accent-muted'
                        : 'text-text-tertiary hover:text-text-secondary hover:bg-bg-surface-hover'
                }`}
                title="Export or share this response"
                aria-haspopup="menu"
                aria-expanded={open}
            >
                <Share2 size={13} />
            </button>

            {open && (
                <div
                    className="absolute left-0 top-full mt-1 w-60 z-50 rounded-lg border border-border bg-bg-elevated shadow-lg overflow-hidden animate-slide-up"
                    role="menu"
                >
                    <div className="px-3 py-2 border-b border-border">
                        <span className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider">
                            Export
                        </span>
                    </div>

                    <button className={itemClass} onClick={handleCopyMarkdown} role="menuitem">
                        {copiedMd ? (
                            <Check size={14} className="text-success shrink-0" />
                        ) : (
                            <Copy size={14} className="shrink-0" />
                        )}
                        <span>{copiedMd ? 'Copied Markdown' : 'Copy as Markdown'}</span>
                    </button>

                    <button
                        className={itemClass}
                        onClick={() => exportResponseAsMarkdown(content, responseTitle)}
                        role="menuitem"
                    >
                        <FileText size={14} className="shrink-0" />
                        <span>Download .md</span>
                    </button>

                    <button
                        className={itemClass}
                        onClick={() => exportResponseAsHtml(content, responseTitle)}
                        role="menuitem"
                    >
                        <FileCode size={14} className="shrink-0" />
                        <span>Download .html</span>
                    </button>

                    <button
                        className={itemClass}
                        onClick={() => exportAsZip(content, responseTitle)}
                        role="menuitem"
                    >
                        <Archive size={14} className="shrink-0" />
                        <span>Download .zip</span>
                    </button>

                    <div className="border-t border-border">
                        {share.status !== 'done' && (
                            <button
                                className={itemClass}
                                onClick={handleShare}
                                disabled={share.status === 'sharing'}
                                role="menuitem"
                            >
                                {share.status === 'sharing' ? (
                                    <Loader2 size={14} className="shrink-0 animate-spin text-accent" />
                                ) : (
                                    <Globe size={14} className="shrink-0 text-accent" />
                                )}
                                <span className="text-text-primary">
                                    {share.status === 'sharing' ? 'Publishing…' : 'Share as web app'}
                                </span>
                            </button>
                        )}

                        {share.status === 'error' && (
                            <div className="flex items-start gap-2 px-3 py-2 text-[12px] text-error">
                                <AlertCircle size={13} className="shrink-0 mt-0.5" />
                                <span className="break-words">{share.message}</span>
                            </div>
                        )}

                        {share.status === 'done' && (
                            <div className="p-3 space-y-2">
                                <div className="flex items-center justify-between">
                                    <span className="text-[11px] font-medium text-success uppercase tracking-wider flex items-center gap-1">
                                        <Check size={12} /> Published
                                    </span>
                                    <button
                                        onClick={() => setShare({ status: 'idle' })}
                                        className="text-text-tertiary hover:text-text-secondary transition-colors"
                                        title="Dismiss"
                                    >
                                        <X size={13} />
                                    </button>
                                </div>
                                <div className="flex items-center gap-1.5 rounded-md border border-border bg-bg-surface px-2 py-1.5">
                                    <LinkIcon size={12} className="shrink-0 text-text-tertiary" />
                                    <a
                                        href={share.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex-1 min-w-0 truncate text-[12px] text-accent-hover hover:underline"
                                        title={share.url}
                                    >
                                        {share.url}
                                    </a>
                                    <button
                                        onClick={handleCopyLink}
                                        className="shrink-0 p-1 rounded text-text-tertiary hover:text-text-secondary hover:bg-bg-surface-hover transition-colors"
                                        title="Copy link"
                                    >
                                        {copiedLink ? (
                                            <Check size={12} className="text-success" />
                                        ) : (
                                            <Copy size={12} />
                                        )}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
