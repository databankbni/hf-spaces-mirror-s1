import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Tester leaves feedback (requires the X-Test-Key header).
export async function POST(request: Request) {
  const key = request.headers.get("x-test-key") ?? "";
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Test-Key": key },
      body: JSON.stringify(body),
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ error: "unreachable" }, { status: 503 });
  }
}
