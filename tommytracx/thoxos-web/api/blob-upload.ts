import { put } from '@vercel/blob';

/**
 * Vercel serverless function (Node.js runtime, web-standard signature).
 *
 * Uploads a text or base64 payload to Vercel Blob and returns its public URL.
 * The Blob token is read exclusively from the server environment — it is NEVER
 * exposed to the browser and must never be hardcoded here.
 *
 * POST body: { filename: string, contentType?: string, text?: string, base64?: string }
 *   -> 200 { url }
 *   -> 400 bad / missing input
 *   -> 503 BLOB_READ_WRITE_TOKEN not configured
 *   -> 502 upstream upload failure
 */

interface UploadBody {
    filename?: unknown;
    contentType?: unknown;
    text?: unknown;
    base64?: unknown;
}

export async function POST(request: Request): Promise<Response> {
    const token = process.env.BLOB_READ_WRITE_TOKEN;
    if (!token) {
        return json(
            { error: 'Blob storage is not configured (BLOB_READ_WRITE_TOKEN is unset).' },
            503,
        );
    }

    let body: UploadBody;
    try {
        body = (await request.json()) as UploadBody;
    } catch {
        return json({ error: 'Request body must be valid JSON.' }, 400);
    }

    const { filename, contentType, text, base64 } = body;

    if (typeof filename !== 'string' || filename.trim() === '') {
        return json({ error: 'A non-empty "filename" is required.' }, 400);
    }
    if (typeof text !== 'string' && typeof base64 !== 'string') {
        return json({ error: 'Provide either a "text" or "base64" body.' }, 400);
    }

    const resolvedContentType =
        typeof contentType === 'string' && contentType.trim() !== ''
            ? contentType
            : 'application/octet-stream';

    let payload: string | Buffer;
    if (typeof base64 === 'string') {
        try {
            payload = Buffer.from(base64, 'base64');
        } catch {
            return json({ error: 'Invalid base64 payload.' }, 400);
        }
    } else {
        payload = text as string;
    }

    try {
        const result = await put(sanitizeFilename(filename), payload, {
            access: 'public',
            contentType: resolvedContentType,
            addRandomSuffix: true,
            token,
        });
        return json({ url: result.url }, 200);
    } catch (err) {
        const message = err instanceof Error ? err.message : 'Upload to Blob storage failed.';
        return json({ error: message }, 502);
    }
}

/** Keep pathnames safe: strip anything unusual, forbid leading slashes, bound length. */
function sanitizeFilename(name: string): string {
    const cleaned = name
        .trim()
        .replace(/[^a-zA-Z0-9._/-]+/g, '-')
        .replace(/^\/+/, '')
        .replace(/\.{2,}/g, '.')
        .slice(0, 200);
    return cleaned || 'artifact';
}

function json(data: unknown, status: number): Response {
    return new Response(JSON.stringify(data), {
        status,
        headers: { 'content-type': 'application/json; charset=utf-8' },
    });
}
