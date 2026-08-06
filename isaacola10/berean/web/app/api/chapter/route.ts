import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Returns a full chapter of a translation (for the context / chapter view).
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const bookNo = params.get("book_no");
  const chapter = params.get("chapter");
  const version = params.get("version") ?? "KJV";

  if (!bookNo || !chapter) {
    return NextResponse.json(
      { error: "book_no and chapter are required" },
      { status: 400 },
    );
  }

  const qs = new URLSearchParams({
    book_no: bookNo,
    chapter,
    version,
  }).toString();

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/chapter?${qs}`, {
      cache: "no-store",
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json(
      { error: "Could not reach the model service." },
      { status: 503 },
    );
  }
}
