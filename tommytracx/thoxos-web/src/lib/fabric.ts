/**
 * THOX CX Fabric surfaces for the Space runtime — Inbox (completed deliverables + task
 * envelopes) and the Artifacts Library.
 *
 * The record shapes are the CX Fabric contracts (src/lib/types/Fabric.ts, mirrored from
 * `@thox-cx/contracts`). This module deliberately does NOT define a parallel schema: it adapts
 * contract objects to the local store and back. The Space is local-first, so the store is
 * IndexedDB rather than the Fabric's server outbox — but because the shape is the contract, a
 * future server sync is a transport change, not a data migration.
 *
 * Ingest is env-gated: when `THOX_FABRIC_BASE_URL` is configured the Space pulls real agent
 * responses; until then the surfaces show whatever this browser produced locally (exports and
 * shared artifacts), which is honest rather than a fake feed of invented deliverables.
 */
import { db, type InboxItem, type ArtifactRecord } from './db';
import type { AgentResponse, TaskEnvelope, Artifact } from './types/Fabric';

/** Adapt a contract AgentResponse (+ its originating envelope) into a local Inbox row. */
export function inboxItemFromResponse(
    response: AgentResponse,
    envelope?: Pick<TaskEnvelope, 'objective' | 'sensitivity' | 'priority'>
): InboxItem {
    return {
        id: response.run_id ?? `${response.task_id}:${response.agent_id}`,
        taskId: response.task_id,
        agentId: response.agent_id,
        status: response.status,
        objective: envelope?.objective ?? response.summary ?? '(no objective recorded)',
        summary: response.summary,
        confidence: response.confidence,
        sensitivity: envelope?.sensitivity,
        priority: envelope?.priority,
        artifactIds: (response.artifacts ?? []).map((a) => a.artifact_id),
        read: false,
        createdAt: Date.now(),
    };
}

/** Adapt a contract Artifact into a local library row. */
export function artifactRecordFrom(
    artifact: Artifact,
    extra: { title?: string; conversationId?: string; mimeType?: string; sizeBytes?: number } = {}
): ArtifactRecord {
    return {
        id: artifact.artifact_id,
        type: artifact.type,
        title: extra.title ?? artifact.ref ?? artifact.artifact_id,
        ref: artifact.ref,
        sensitivity: artifact.sensitivity,
        conversationId: extra.conversationId,
        mimeType: extra.mimeType,
        sizeBytes: extra.sizeBytes,
        createdAt: Date.now(),
    };
}

// ─── Local store ───

export async function listInbox(): Promise<InboxItem[]> {
    return db.inbox.orderBy('createdAt').reverse().toArray();
}

export async function unreadInboxCount(): Promise<number> {
    return db.inbox.filter((i) => !i.read).count();
}

export async function markInboxRead(id: string): Promise<void> {
    await db.inbox.update(id, { read: true });
}

export async function markAllInboxRead(): Promise<void> {
    const all = await db.inbox.toArray();
    await Promise.all(all.filter((i) => !i.read).map((i) => db.inbox.update(i.id, { read: true })));
}

export async function putInboxItem(item: InboxItem): Promise<void> {
    await db.inbox.put(item);
}

export async function listArtifacts(): Promise<ArtifactRecord[]> {
    return db.artifacts.orderBy('createdAt').reverse().toArray();
}

export async function putArtifact(record: ArtifactRecord): Promise<void> {
    await db.artifacts.put(record);
}

export async function deleteArtifact(id: string): Promise<void> {
    await db.artifacts.delete(id);
}

/**
 * Record an artifact the user just produced in this Space (an export, or a "share as web app"
 * blob). This is what populates the library today, with no Fabric server involved.
 */
export async function recordLocalArtifact(opts: {
    type: string;
    title: string;
    ref?: string;
    conversationId?: string;
    mimeType?: string;
    sizeBytes?: number;
}): Promise<ArtifactRecord> {
    const record: ArtifactRecord = {
        id: `art_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
        type: opts.type,
        title: opts.title,
        ref: opts.ref,
        // Locally-produced artifacts are internal until the user deliberately shares them; a
        // blob URL is public by construction, so mark that honestly.
        sensitivity: opts.ref?.startsWith('http') ? 'public' : 'internal',
        conversationId: opts.conversationId,
        mimeType: opts.mimeType,
        sizeBytes: opts.sizeBytes,
        createdAt: Date.now(),
    };
    await putArtifact(record);
    return record;
}

// ─── Optional Fabric ingest ───

export interface FabricSyncResult {
    configured: boolean;
    imported: number;
    error?: string;
}

/**
 * Pull completed deliverables from a CX Fabric endpoint, if this deployment has one.
 *
 * Returns `configured: false` rather than throwing when no endpoint is set — an unconfigured
 * Fabric is the expected state for a public Space, not an error the user should see.
 */
export async function syncFabricInbox(): Promise<FabricSyncResult> {
    let base = '';
    try {
        const res = await fetch('/api/v2/thoxroute/status');
        if (res.ok) {
            const status = await res.json();
            base = status.fabricBaseUrl || '';
        }
    } catch {
        return { configured: false, imported: 0 };
    }
    if (!base) return { configured: false, imported: 0 };

    try {
        const res = await fetch(`${base.replace(/\/$/, '')}/inbox`);
        if (!res.ok) return { configured: true, imported: 0, error: `Fabric ${res.status}` };
        const payload = (await res.json()) as { responses?: AgentResponse[] };
        const items = (payload.responses ?? []).map((r) => inboxItemFromResponse(r));
        await Promise.all(items.map(putInboxItem));
        return { configured: true, imported: items.length };
    } catch (err) {
        return { configured: true, imported: 0, error: err instanceof Error ? err.message : String(err) };
    }
}
