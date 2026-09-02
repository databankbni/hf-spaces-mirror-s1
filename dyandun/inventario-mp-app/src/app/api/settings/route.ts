import { NextResponse } from "next/server";

// Configuraciones sueltas compartidas (clave -> valor JSON) en Supabase. Hoy se
// usa para la flota (key='fleet'). Fuente de verdad compartida entre usuarios.
// Usa la llave secreta SOLO en el servidor. Degrada con ok:false si falta config.

const TABLE = "inventario_mp_app_settings";

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para compartir esta configuración entre usuarios.";

// GET ?key=fleet -> devuelve el valor JSON de esa clave (o null si no existe).
export async function GET(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, value: null });
  }

  const settingKey = new URL(request.url).searchParams.get("key") ?? "";
  if (!settingKey) {
    return NextResponse.json({ ok: false, message: "Falta el parámetro key.", value: null });
  }

  const response = await fetch(
    `${url}/rest/v1/${TABLE}?key=eq.${encodeURIComponent(settingKey)}&select=value`,
    { headers: { apikey: key!, Authorization: `Bearer ${key!}` }, cache: "no-store" }
  );

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, value: null });
  }

  const rows = await response.json();
  const value = Array.isArray(rows) && rows.length > 0 ? rows[0].value : null;
  return NextResponse.json({ ok: true, value });
}

// POST { key, value } -> upsert de la clave.
export async function POST(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE });
  }

  const body = await request.json();
  const settingKey = String(body.key ?? "").trim();
  if (!settingKey) {
    return NextResponse.json({ ok: false, message: "Falta key." });
  }

  const row = {
    key: settingKey,
    value: body.value ?? {},
    updated_at: new Date().toISOString()
  };

  const response = await fetch(`${url}/rest/v1/${TABLE}?on_conflict=key`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key!}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal"
    },
    body: JSON.stringify(row)
  });

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}` });
  }

  return NextResponse.json({ ok: true });
}
