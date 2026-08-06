import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Active-listening detection: forwards a transcript chunk; the backend decides
// whether it references scripture (and filters out everyday speech / noise).
export async function POST(request: Request) {
  let body: { text?: unknown; version?: unknown; ref_style?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ matched: false }, { status: 400 });
  }
  const text = typeof body.text === "string" ? body.text : "";
  const version =
    typeof body.version === "string" && body.version ? body.version : "all";
  const ref_style =
    body.ref_style === "v" ? "v" : "colon";

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/listen`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Test-Key": request.headers.get("x-test-key") ?? "",
      },
      body: JSON.stringify({ text, version, ref_style }),
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ matched: false }, { status: 503 });
  }
}
