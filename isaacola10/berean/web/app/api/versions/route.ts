import { NextResponse } from "next/server";

const PYTHON_API_URL =
  process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Lists the translations available to search. Read at page load so the UI
// reflects whatever versions are present on the backend (fully dynamic).
export async function GET() {
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/versions`, {
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json({ versions: [] }, { status: 502 });
    }
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ versions: [] }, { status: 503 });
  }
}
