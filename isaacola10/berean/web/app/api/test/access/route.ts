import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Validate a test key and return its per-feature permissions.
export async function POST(request: Request) {
  const key = request.headers.get("x-test-key") ?? "";
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/test/access`, {
      method: "POST",
      headers: { "X-Test-Key": key },
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ valid: false }, { status: 503 });
  }
}
