import { NextResponse } from "next/server";

// Where the Python (FastAPI) model service lives. Configurable per env.
const PYTHON_API_URL =
  process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// This route runs server-side and proxies the recorded audio to the Python
// model service, so the browser only ever talks to the Next.js origin
// (no CORS, and the backend URL stays server-only).
export async function POST(request: Request) {
  const incoming = await request.formData();
  const audio = incoming.get("audio");

  if (!(audio instanceof Blob)) {
    return NextResponse.json(
      { error: "No audio file provided" },
      { status: 400 },
    );
  }

  const forwarded = new FormData();
  forwarded.append("audio", audio, "recording.webm");

  // Pass the chosen translation + spoken language through (the Python
  // endpoint reads `version` and `lang`; both default sensibly).
  const incomingParams = new URL(request.url).searchParams;
  const version = incomingParams.get("version") ?? "all";
  const lang = incomingParams.get("lang") ?? "auto";
  const scope = incomingParams.get("scope") ?? "all";
  const qs = new URLSearchParams({ version, lang, scope }).toString();

  try {
    const res = await fetch(`${PYTHON_API_URL}/api/predict?${qs}`, {
      method: "POST",
      headers: { "X-Test-Key": request.headers.get("x-test-key") ?? "" },
      body: forwarded,
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { error: "Model service error", detail },
        { status: 502 },
      );
    }

    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json(
      {
        error:
          "Could not reach the model service. Is the Python server running on " +
          PYTHON_API_URL +
          "?",
      },
      { status: 503 },
    );
  }
}
