import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Public feature flags the UI reads to toggle features / show maintenance.
export async function GET() {
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/config`, { cache: "no-store" });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json(
      { ask_enabled: true, crossrefs_enabled: true, similar_enabled: true, maintenance: false },
      { status: 200 },
    );
  }
}
