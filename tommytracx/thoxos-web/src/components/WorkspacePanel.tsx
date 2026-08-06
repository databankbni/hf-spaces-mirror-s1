/**
 * THOX Workspace — the DigitalHumans surfaces that fit a local-first Space runtime:
 *   • Inbox     — completed deliverables + task envelopes, in CX Fabric contract shape
 *   • Artifacts — the artifacts library (exports and shared web apps produced here)
 *   • Fleet     — the live ThoxRoute serving view: what can answer, and why not if it can't
 *
 * The Fleet tab is deliberately blunt about unavailability. A model that is configured but
 * unreachable, or gated off, is more useful to see with its reason than hidden — that is the
 * difference between an operator console and a brochure.
 */
import { useEffect, useState } from 'react';
import { X, Inbox as InboxIcon, Package, Radio, RefreshCw, Trash2, ExternalLink } from 'lucide-react';
import { useApp } from '../context/AppContext';
import {
    listInbox,
    listArtifacts,
    markAllInboxRead,
    markInboxRead,
    deleteArtifact,
    syncFabricInbox,
    type FabricSyncResult,
} from '../lib/fabric';
import type { InboxItem, ArtifactRecord } from '../lib/db';
import { getThoxRouteStatus, type ThoxRouteStatus } from '../lib/thoxroute/client';
import {
    probeWebGPU,
    loadWebGPUModel,
    isWebGPUModelLoaded,
    onWebGPUProgress,
    type WebGPUProbe,
    type WebGPULoadProgress,
} from '../lib/thoxroute/webgpu';

type Tab = 'inbox' | 'artifacts' | 'fleet';

const REASON_LABEL: Record<string, string> = {
    endpoint_unset: 'endpoint not configured',
    gated_disabled: 'gated — not enabled here',
    runtime_missing: 'in-browser runtime not shipped',
    duplicate_id: 'duplicate id in registry',
};

export default function WorkspacePanel({ initialTab = 'inbox' }: { initialTab?: Tab }) {
    const { setActiveModal } = useApp();
    const [tab, setTab] = useState<Tab>(initialTab);

    const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
        { id: 'inbox', label: 'Inbox', icon: <InboxIcon size={14} /> },
        { id: 'artifacts', label: 'Artifacts', icon: <Package size={14} /> },
        { id: 'fleet', label: 'Fleet', icon: <Radio size={14} /> },
    ];

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60" onClick={() => setActiveModal(null)} />
            <div className="relative w-full max-w-2xl max-h-[85vh] glass rounded-xl flex flex-col animate-slide-up overflow-hidden">
                <div className="flex items-center justify-between px-5 py-4 border-b border-border">
                    <h2 className="text-base font-semibold text-text-primary">THOX Workspace</h2>
                    <button
                        onClick={() => setActiveModal(null)}
                        className="p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-surface-hover transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="flex border-b border-border px-5 gap-1 overflow-x-auto">
                    {tabs.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
                                tab === t.id
                                    ? 'border-accent text-accent'
                                    : 'border-transparent text-text-secondary hover:text-text-primary'
                            }`}
                        >
                            {t.icon}
                            {t.label}
                        </button>
                    ))}
                </div>

                <div className="flex-1 overflow-y-auto p-5">
                    {tab === 'inbox' && <InboxTab />}
                    {tab === 'artifacts' && <ArtifactsTab />}
                    {tab === 'fleet' && <FleetTab />}
                </div>
            </div>
        </div>
    );
}

// ─── Inbox ───

function InboxTab() {
    const [items, setItems] = useState<InboxItem[]>([]);
    const [sync, setSync] = useState<FabricSyncResult | null>(null);
    const [busy, setBusy] = useState(false);

    const load = () => listInbox().then(setItems);
    useEffect(() => {
        load();
    }, []);

    const handleSync = async () => {
        setBusy(true);
        const result = await syncFabricInbox();
        setSync(result);
        await load();
        setBusy(false);
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-text-tertiary">
                    Completed deliverables and task envelopes, in CX Fabric contract shape.
                </p>
                <div className="flex items-center gap-2 shrink-0">
                    <button
                        onClick={handleSync}
                        disabled={busy}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg bg-bg-surface border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface-hover transition-colors disabled:opacity-50"
                    >
                        <RefreshCw size={12} className={busy ? 'animate-spin' : ''} />
                        Sync
                    </button>
                    {items.some((i) => !i.read) && (
                        <button
                            onClick={() => markAllInboxRead().then(load)}
                            className="px-2.5 py-1.5 text-xs rounded-lg text-accent hover:bg-accent-muted transition-colors"
                        >
                            Mark all read
                        </button>
                    )}
                </div>
            </div>

            {sync && !sync.configured && (
                <div className="callout-glass callout-info text-xs">
                    No CX Fabric endpoint is configured for this Space, so the Inbox shows only what
                    was produced locally. Set <code className="inline-code">THOX_FABRIC_BASE_URL</code> to
                    ingest real agent deliverables.
                </div>
            )}
            {sync?.error && (
                <div className="callout-glass callout-warning text-xs">Fabric sync: {sync.error}</div>
            )}

            {items.length === 0 ? (
                <div className="text-center py-10">
                    <InboxIcon size={30} className="mx-auto mb-3 text-text-tertiary" />
                    <p className="text-sm text-text-tertiary">Inbox is empty</p>
                    <p className="text-[11px] text-text-tertiary mt-1">
                        Deliverables appear here when a Fabric endpoint is connected.
                    </p>
                </div>
            ) : (
                <div className="space-y-2">
                    {items.map((item) => (
                        <button
                            key={item.id}
                            onClick={() => markInboxRead(item.id).then(load)}
                            className={`w-full text-left p-3 rounded-xl border transition-colors ${
                                item.read
                                    ? 'border-border bg-bg-surface hover:bg-bg-surface-hover'
                                    : 'border-accent/30 bg-accent-subtle hover:bg-accent-muted'
                            }`}
                        >
                            <div className="flex items-start justify-between gap-2">
                                <span className="text-sm text-text-primary font-medium">{item.objective}</span>
                                <StatusChip status={item.status} />
                            </div>
                            {item.summary && (
                                <p className="text-[11px] text-text-secondary mt-1 line-clamp-2">{item.summary}</p>
                            )}
                            <div className="flex items-center gap-3 mt-2 text-[10px] text-text-tertiary font-mono">
                                <span>{item.agentId}</span>
                                {typeof item.confidence === 'number' && (
                                    <span>conf {item.confidence.toFixed(2)}</span>
                                )}
                                {item.sensitivity && <span>{item.sensitivity}</span>}
                            </div>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

function StatusChip({ status }: { status: InboxItem['status'] }) {
    const tone =
        status === 'completed'
            ? 'bg-success-muted text-success'
            : status === 'failed' || status === 'blocked'
              ? 'bg-error-muted text-error'
              : 'bg-warning-muted text-warning';
    return (
        <span className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-medium ${tone}`}>
            {status.replace('_', ' ')}
        </span>
    );
}

// ─── Artifacts ───

function ArtifactsTab() {
    const [items, setItems] = useState<ArtifactRecord[]>([]);
    const load = () => listArtifacts().then(setItems);
    useEffect(() => {
        load();
    }, []);

    return (
        <div className="space-y-4">
            <p className="text-[11px] text-text-tertiary">
                Exports and shared web apps produced in this workspace. Stored in CX Fabric{' '}
                <code className="inline-code">Artifact</code> shape.
            </p>

            {items.length === 0 ? (
                <div className="text-center py-10">
                    <Package size={30} className="mx-auto mb-3 text-text-tertiary" />
                    <p className="text-sm text-text-tertiary">No artifacts yet</p>
                    <p className="text-[11px] text-text-tertiary mt-1">
                        Export a response or share it as a web app to add one.
                    </p>
                </div>
            ) : (
                <div className="space-y-2">
                    {items.map((a) => (
                        <div
                            key={a.id}
                            className="flex items-center gap-3 p-3 rounded-xl border border-border bg-bg-surface"
                        >
                            <div className="flex-1 min-w-0">
                                <p className="text-sm text-text-primary truncate">{a.title}</p>
                                <div className="flex items-center gap-3 mt-0.5 text-[10px] text-text-tertiary font-mono">
                                    <span>{a.type}</span>
                                    {a.sensitivity && <span>{a.sensitivity}</span>}
                                    <span>{new Date(a.createdAt).toLocaleDateString()}</span>
                                </div>
                            </div>
                            {a.ref?.startsWith('http') && (
                                <a
                                    href={a.ref}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="p-1.5 rounded-lg text-text-tertiary hover:text-accent transition-colors"
                                >
                                    <ExternalLink size={14} />
                                </a>
                            )}
                            <button
                                onClick={() => deleteArtifact(a.id).then(load)}
                                className="p-1.5 rounded-lg text-text-tertiary hover:text-error transition-colors"
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ─── Fleet (ThoxRoute serving view) ───

function FleetTab() {
    const [status, setStatus] = useState<ThoxRouteStatus | null>(null);
    useEffect(() => {
        getThoxRouteStatus(true).then(setStatus);
    }, []);

    if (!status) return <p className="text-sm text-text-tertiary">Loading fleet…</p>;

    const available = status.models.filter((m) => m.available);
    const blocked = status.models.filter((m) => !m.available);

    return (
        <div className="space-y-5">
            <OnDeviceTier />
            <div className="flex items-center gap-3 flex-wrap text-[11px] text-text-tertiary">
                <span>
                    registry <span className="text-text-secondary font-mono">v{status.version}</span>
                </span>
                <span>
                    routing{' '}
                    <span className="text-text-secondary">
                        {status.classifier?.configured ? 'classifier model' : 'local heuristics'}
                    </span>
                </span>
                <span>
                    gated line{' '}
                    <span className={status.gatedEnabled ? 'text-warning' : 'text-text-secondary'}>
                        {status.gatedEnabled ? 'enabled' : 'off'}
                    </span>
                </span>
            </div>

            <div>
                <h3 className="text-xs font-semibold text-text-primary mb-2 uppercase tracking-wider">
                    Serving ({available.length})
                </h3>
                {available.length === 0 ? (
                    <p className="text-xs text-text-tertiary">
                        No THOX endpoint is configured on this deployment yet.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {available.map((r) => (
                            <div
                                key={r.model.id}
                                className="p-3 rounded-xl border border-accent/25 bg-accent-subtle"
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-sm text-text-primary font-medium">
                                        {r.model.displayName}
                                    </span>
                                    <span className="text-[10px] font-mono text-accent">
                                        {r.model.locality}
                                    </span>
                                </div>
                                {r.model.description && (
                                    <p className="text-[11px] text-text-secondary mt-1">{r.model.description}</p>
                                )}
                                {(r.fallbacks ?? []).map((f, i) => (
                                    <p
                                        key={f.baseURL}
                                        className="text-[10px] font-mono text-warning mt-1.5"
                                    >
                                        ↳ fallback {i + 1}: {f.tier ?? 'configured'} ·{' '}
                                        {f.displayName ?? f.baseURL.replace(/^https?:\/\//, '')}
                                    </p>
                                ))}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div>
                <h3 className="text-xs font-semibold text-text-secondary mb-2 uppercase tracking-wider">
                    Declared, not serving ({blocked.length})
                </h3>
                <div className="space-y-1.5">
                    {blocked.map((r) => (
                        <div
                            key={r.model.id}
                            className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-border bg-bg-surface"
                        >
                            <span className="text-xs text-text-secondary">{r.model.displayName}</span>
                            <span className="text-[10px] font-mono text-text-tertiary">
                                {REASON_LABEL[r.reason ?? ''] ?? r.reason}
                            </span>
                        </div>
                    ))}
                </div>
                <p className="text-[10px] text-text-tertiary mt-2">
                    Models become available automatically when their endpoint env var is set — no
                    rebuild required.
                </p>
            </div>
        </div>
    );
}


// ─── On-device (WebGPU) tier ───

/**
 * The offline floor, surfaced honestly: it reports what the browser can actually do, and the
 * ~2 GB download is an explicit choice rather than something a remote outage triggers silently.
 */
function OnDeviceTier() {
    const [probe, setProbe] = useState<WebGPUProbe | null>(null);
    const [loaded, setLoaded] = useState(isWebGPUModelLoaded());
    const [progress, setProgress] = useState<WebGPULoadProgress | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        probeWebGPU().then(setProbe);
        return onWebGPUProgress((p) => setProgress(p));
    }, []);

    const start = async () => {
        setLoading(true);
        setError(null);
        try {
            await loadWebGPUModel();
            setLoaded(true);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    };

    const supported = probe?.supported === true;
    return (
        <div
            className={`p-3 rounded-xl border ${
                loaded ? 'border-accent/30 bg-accent-subtle' : 'border-border bg-bg-surface'
            }`}
        >
            <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-text-primary font-medium">On-device (WebGPU)</span>
                <span className="text-[10px] font-mono text-text-tertiary">
                    {loaded ? 'resident' : supported ? 'available' : (probe?.reason ?? 'probing…')}
                </span>
            </div>
            <p className="text-[11px] text-text-secondary mt-1">
                Last tier in the cascade. Runs Gemma-4 fully in this browser — answers with no
                network at all, after a one-time ~2 GB download.
            </p>
            {!supported && probe && (
                <p className="text-[10px] font-mono text-warning mt-1.5">
                    unavailable here: {probe.reason}
                    {probe.detail ? ` — ${probe.detail}` : ''}
                </p>
            )}
            {supported && !loaded && (
                <button
                    onClick={start}
                    disabled={loading}
                    className="mt-2 px-3 py-1.5 text-xs rounded-lg bg-accent text-white hover:bg-accent-hover disabled:opacity-50 transition-colors"
                >
                    {loading
                        ? `${progress?.message ?? 'Loading'}… ${
                              progress?.fraction != null ? `${Math.round(progress.fraction * 100)}%` : ''
                          }`
                        : 'Load on-device model'}
                </button>
            )}
            {error && <p className="text-[10px] font-mono text-error mt-1.5">{error}</p>}
        </div>
    );
}
