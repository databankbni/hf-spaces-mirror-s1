import Dexie, { type Table } from 'dexie';

export interface Conversation {
    id: string;
    title: string;
    createdAt: number;
    updatedAt: number;
    canvasId: string | null;
    providerId: string;
    modelId: string;
    webSearchEnabled: boolean;
}

export interface Attachment {
    type: 'image' | 'file';
    name: string;
    mimeType: string;
    dataUrl: string; // data:mime;base64,...
}

export interface Message {
    id: string;
    conversationId: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    attachments?: Attachment[];
    sources?: SearchSource[];
    createdAt: number;
    /** ThoxRoute decision for this turn, e.g. "hard → ThoxIntel 27B". Absent for pinned models. */
    routedVia?: string;
}

export interface Canvas {
    id: string;
    name: string;
    spec: CanvasSpec;
    createdAt: number;
    updatedAt: number;
}

export interface SearchSource {
    title: string;
    url: string;
    content: string;
    score?: number;
}

export interface CanvasSpec {
    tokens: {
        colors: Record<string, string>;
        typography: {
            fontFamily: string;
            fontFamilyMono: string;
            scale: Record<string, string>;
        };
        spacing: Record<string, string>;
        radius: Record<string, string>;
        shadows: Record<string, string>;
    };
    components: {
        card: Record<string, string>;
        callout: Record<string, Record<string, string>>;
        table: Record<string, string>;
        codeBlock: Record<string, string>;
        input: Record<string, string>;
        button: Record<string, Record<string, string>>;
    };
    decorations?: {
        backgroundGradient?: string;
        backgroundPattern?: 'dots' | 'grid' | 'none';
        messageGlow?: boolean;
        animatedAccents?: boolean;
    };
}

// ─── THOX CX Fabric surfaces (DigitalHumans) ───
// Inbox items and artifacts are stored in the SHAPE of the CX Fabric contracts
// (src/lib/types/Fabric.ts, mirrored from @thox-cx/contracts). The Space is local-first, so these
// live in IndexedDB rather than the Fabric's server outbox — but the record shape is the contract,
// so a future sync is a transport change, not a data migration.

export interface InboxItem {
    /** Mirrors AgentResponse.task_id — the envelope this deliverable answers. */
    id: string;
    taskId: string;
    agentId: string;
    /** AgentResponseStatus from the contract. */
    status: 'completed' | 'needs_handoff' | 'blocked' | 'failed' | 'awaiting_approval';
    objective: string;
    summary?: string;
    confidence?: number;
    sensitivity?: 'public' | 'internal' | 'confidential' | 'restricted';
    priority?: 'low' | 'normal' | 'high' | 'urgent';
    artifactIds?: string[];
    /** Local-only: unread state for the Inbox badge. */
    read?: boolean;
    createdAt: number;
}

export interface ArtifactRecord {
    /** Mirrors Artifact.artifact_id. */
    id: string;
    /** Mirrors Artifact.type — free-form in the contract (e.g. "document", "web_app", "export"). */
    type: string;
    title: string;
    /** Mirrors Artifact.ref — a URL for shared/blob artifacts, or a local marker. */
    ref?: string;
    sensitivity?: 'public' | 'internal' | 'confidential' | 'restricted';
    /** Origin conversation, when the artifact came from a chat turn. */
    conversationId?: string;
    mimeType?: string;
    sizeBytes?: number;
    createdAt: number;
}

class ThoxosDB extends Dexie {
    conversations!: Table<Conversation>;
    messages!: Table<Message>;
    canvases!: Table<Canvas>;
    inbox!: Table<InboxItem>;
    artifacts!: Table<ArtifactRecord>;

    constructor() {
        super('thoxos-db');
        this.version(1).stores({
            conversations: 'id, updatedAt',
            messages: 'id, conversationId, createdAt',
            canvases: 'id, updatedAt',
        });
        // v2 is purely additive — existing conversations/messages are untouched, so an existing
        // visitor keeps their full chat history across this upgrade.
        this.version(2).stores({
            conversations: 'id, updatedAt',
            messages: 'id, conversationId, createdAt',
            canvases: 'id, updatedAt',
            inbox: 'id, createdAt, status, read',
            artifacts: 'id, createdAt, type, conversationId',
        });
    }
}

export const db = new ThoxosDB();
