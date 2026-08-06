import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

const VIDEO_ROOT = path.resolve(
  process.env.TRIWORLDBENCH_VIDEO_ROOT || path.join(process.cwd(), "media", "video-cases")
);

function safeVideoPath(category: string, fileName: string): string | null {
  if (!["clean", "random"].includes(category)) return null;
  if (!/^[a-zA-Z0-9()[\]._ -]+\.mp4$/.test(fileName)) return null;

  const resolved = path.resolve(VIDEO_ROOT, category, fileName);
  const categoryRoot = path.resolve(VIDEO_ROOT, category);
  if (!resolved.startsWith(categoryRoot + path.sep)) return null;
  return resolved;
}

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ category: string; fileName: string }> }
) {
  const { category, fileName } = await context.params;
  const videoPath = safeVideoPath(category, fileName);
  if (!videoPath) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  try {
    const file = await readFile(videoPath);
    return new NextResponse(file, {
      headers: {
        "Content-Type": "video/mp4",
        "Content-Disposition": `inline; filename="${fileName.replace(/"/g, "")}"`,
        "Content-Length": String(file.byteLength),
        "Cache-Control": "private, no-store, max-age=0",
        "Accept-Ranges": "none",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "picture-in-picture=()",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
      },
    });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
}
