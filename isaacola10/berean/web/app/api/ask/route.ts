import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";
const MAX_QUESTION_LEN = 500;

// Simple in-memory per-IP rate limiter (the AI endpoint is the cost center).
// Persists across requests in the long-running Node process.
const RATE_LIMIT = 15; // requests
const RATE_WINDOW_MS = 60_000; // per minute
const hits = new Map<string, number[]>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < RATE_WINDOW_MS);
  recent.push(now);
  hits.set(ip, recent);
  return recent.length > RATE_LIMIT;
}

export async function POST(request: Request) {
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip") ||
    "anon";

  if (rateLimited(ip)) {
    return NextResponse.json(
      { error: "Too many questions — please wait a minute and try again." },
      { status: 429 },
    );
  }

  let body: { question?: unknown; version?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  let question = typeof body.question === "string" ? body.question.trim() : "";
  if (!question) {
    return NextResponse.json({ error: "No question provided" }, { status: 400 });
  }
  question = question.slice(0, MAX_QUESTION_LEN);
  const version =
    typeof body.version === "string" && body.version ? body.version : "all";

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Test-Key": request.headers.get("x-test-key") ?? "",
      },
      body: JSON.stringify({ question, version }),
    });
    // Stream the SSE body straight through to the browser.
    return new Response(res.body, {
      status: res.status,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch {
    return NextResponse.json(
      { error: "Could not reach the Q&A service." },
      { status: 503 },
    );
  }
}
