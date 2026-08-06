const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

// Catch-all proxy for the Sermon Studio API. Forwards method, path, body, and
// the Clerk session token (Authorization: Bearer) to the Python backend.
async function forward(request: Request, path: string[] | undefined): Promise<Response> {
  const target = `${PYTHON_API_URL}/api/sermons${path?.length ? "/" + path.join("/") : ""}`;
  const headers: Record<string, string> = {};
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;

  const init: RequestInit = { method: request.method, headers };
  if (!["GET", "DELETE", "HEAD"].includes(request.method)) {
    headers["Content-Type"] = "application/json";
    init.body = await request.text();
  }

  try {
    const res = await fetch(target, init);
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "Sermon service unreachable" }, { status: 503 });
  }
}

type Ctx = { params: Promise<{ path?: string[] }> };

export async function GET(req: Request, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: Request, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function PUT(req: Request, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function DELETE(req: Request, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
