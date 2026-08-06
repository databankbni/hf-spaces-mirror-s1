import { NextResponse } from "next/server";

const PYTHON_API_URL =
  process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Text path: forwards a typed query to the Python model service.
export async function POST(request: Request) {
  let body: { text?: unknown; version?: unknown; scope?: unknown; top_k?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (!text) {
    return NextResponse.json({ error: "No text provided" }, { status: 400 });
  }
  const version =
    typeof body.version === "string" && body.version ? body.version : "all";
  const scope =
    typeof body.scope === "string" && body.scope ? body.scope : "all";
  const top_k = typeof body.top_k === "number" ? body.top_k : 5;

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Test-Key": request.headers.get("x-test-key") ?? "",
      },
      body: JSON.stringify({ text, version, scope, top_k }),
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { error: "Model service error", detail },
        { status: 502 },
      );
    }

    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json(
      {
        error:
          "Could not reach the model service. Is the Python server running on " +
          PYTHON_API_URL +
          "?",
      },
      { status: 503 },
    );
  }
}
