import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Readiness check — the model service loads its index/ASR in the background.
export async function GET() {
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/health`, { cache: "no-store" });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json(
      { status: "unreachable", ready: false, error: "model service unreachable" },
      { status: 503 },
    );
  }
}
