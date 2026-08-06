import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

export async function GET(request: Request) {
  const p = new URL(request.url).searchParams;
  const qs = new URLSearchParams({
    book_no: p.get("book_no") ?? "",
    chapter: p.get("chapter") ?? "",
    verse: p.get("verse") ?? "",
    version: p.get("version") ?? "all",
    top_k: p.get("top_k") ?? "6",
  }).toString();
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/similar?${qs}`, {
      cache: "no-store",
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ results: [] }, { status: 503 });
  }
}
