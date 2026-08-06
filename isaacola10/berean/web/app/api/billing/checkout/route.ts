import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Start a Stripe Checkout session (auth required — token forwarded).
export async function POST(request: Request) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/billing/checkout`, {
      method: "POST",
      headers,
      body: await request.text(),
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ detail: "Billing service unreachable" }, { status: 503 });
  }
}
