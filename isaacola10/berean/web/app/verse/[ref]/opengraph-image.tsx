import { ImageResponse } from "next/og";

export const alt = "Bible verse";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

async function lookup(slug: string) {
  const query = decodeURIComponent(slug).replace(/-/g, " ");
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: query, top_k: 1 }),
      cache: "no-store",
    });
    const data = await res.json();
    return data.results?.[0] ?? null;
  } catch {
    return null;
  }
}

// Shareable verse "card" image (used when the permalink is shared/unfurled).
export default async function Image(props: { params: Promise<{ ref: string }> }) {
  const { ref } = await props.params;
  const v = await lookup(ref);
  const text = v?.text ?? "";
  const reference = v ? `${v.ref}` : "Verseo";
  const version = v?.version ?? "";
  const display = text.length > 240 ? text.slice(0, 237) + "…" : text;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px",
          background: "linear-gradient(135deg, #7c3aed 0%, #c026d3 50%, #ec4899 100%)",
          color: "white",
          fontFamily: "Georgia, serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 30, opacity: 0.85 }}>
          📖&nbsp;&nbsp;Verseo
        </div>
        <div style={{ display: "flex", fontSize: 52, lineHeight: 1.25, fontWeight: 500 }}>
          “{display}”
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 36 }}>
          <span style={{ fontWeight: 700 }}>{reference}</span>
          <span style={{ opacity: 0.8, fontSize: 28 }}>{version}</span>
        </div>
      </div>
    ),
    { ...size },
  );
}
