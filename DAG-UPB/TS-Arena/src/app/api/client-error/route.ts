import { NextRequest, NextResponse } from 'next/server';

/**
 * Sink for client-side exceptions caught by the error boundaries.
 *
 * Writes one line to the container log, which is readable through the Coolify API. That
 * keeps error reporting entirely on UPB infrastructure — no third-party service, and
 * nothing to configure on a host with no outbound internet.
 *
 * This endpoint is public, because the errors worth catching happen before any session
 * exists. So it treats its input as hostile: the body is size-capped, every field is
 * truncated, and the whole route is rate-limited, since its only effect is to write to a
 * log that someone could otherwise flood.
 */

const MAX_BODY_BYTES = 16_000;
const MAX_MESSAGE_CHARS = 500;
const MAX_STACK_CHARS = 4_000;
const MAX_FIELD_CHARS = 300;

// Per-instance throttle. Not a security boundary — a cheap ceiling on log volume.
const WINDOW_MS = 60_000;
const MAX_REPORTS_PER_WINDOW = 60;
let windowStartedAt = 0;
let reportsThisWindow = 0;

function withinRateLimit(now: number): boolean {
  if (now - windowStartedAt > WINDOW_MS) {
    windowStartedAt = now;
    reportsThisWindow = 0;
  }
  reportsThisWindow += 1;
  return reportsThisWindow <= MAX_REPORTS_PER_WINDOW;
}

/** Coerce anything to a single-line, length-capped string. */
function clean(value: unknown, max: number): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}

export async function POST(request: NextRequest) {
  // 204 on every path below: the caller is an error boundary and must never be handed
  // another failure to deal with.
  const ok = new NextResponse(null, { status: 204 });

  if (!withinRateLimit(Date.now())) return ok;

  let raw: string;
  try {
    raw = await request.text();
  } catch {
    return ok;
  }
  if (raw.length > MAX_BODY_BYTES) return ok;

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw);
  } catch {
    return ok;
  }

  const message = clean(body.message, MAX_MESSAGE_CHARS);
  const digest = clean(body.digest, MAX_FIELD_CHARS);
  const pathname = clean(body.pathname, MAX_FIELD_CHARS);
  const userAgent = clean(body.userAgent, MAX_FIELD_CHARS);
  // Newlines are what make a stack readable, so keep them — but cap the length.
  const stack =
    typeof body.stack === 'string' ? body.stack.slice(0, MAX_STACK_CHARS) : '';

  if (!message && !stack && !digest) return ok;

  console.error(
    `CLIENT ERROR: ${JSON.stringify({ message, digest, pathname, userAgent })}` +
      (stack ? `\n${stack}` : ''),
  );

  return ok;
}
