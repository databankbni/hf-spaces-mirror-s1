import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Stripe webhook passthrough. The raw body must be forwarded untouched so the
// backend can verify the stripe-signature header against the exact bytes.
export async function POST(request: Request) {
  const payload = await request.text();
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/billing/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "stripe-signature": request.headers.get("stripe-signature") ?? "",
      },
      body: payload,
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ detail: "unreachable" }, { status: 503 });
  }
}
