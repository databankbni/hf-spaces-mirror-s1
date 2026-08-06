import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/stats`, { cache: "no-store" });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ searches: 0, asks: 0, top: [] }, { status: 503 });
  }
}
