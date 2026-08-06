import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Marks the onboarding walkthrough as seen (forwards the Clerk session token).
export async function POST(request: Request) {
  const headers: Record<string, string> = {};
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/me/onboarded`, {
      method: "POST",
      headers,
      cache: "no-store",
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ ok: false }, { status: 503 });
  }
}
