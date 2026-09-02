import { NextResponse } from "next/server";

// Persiste y consulta la matriz de rutas editable (km, $/km, on/off por par
// origen->destino) en Supabase. Usa la llave secreta SOLO en el servidor.
// Degrada con ok:false si faltan variables, igual que /api/plan.

const TABLE = "inventario_mp_app_routes";

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para guardar la matriz de rutas.";

// GET: devuelve todas las rutas guardadas.
export async function GET() {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, routes: [] });
  }

  const response = await fetch(
    `${url}/rest/v1/${TABLE}?select=origen,destino,km,costo_por_km,enabled`,
    { headers: { apikey: key!, Authorization: `Bearer ${key!}` }, cache: "no-store" }
  );

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, routes: [] });
  }

  const routes = await response.json();
  return NextResponse.json({ ok: true, routes });
}

// POST: upsert de una ruta por (origen, destino).
export async function POST(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE });
  }

  const body = await request.json();
  const origen = String(body.origen ?? "").trim();
  const destino = String(body.destino ?? "").trim();
  if (!origen || !destino) {
    return NextResponse.json({ ok: false, message: "Falta origen o destino." });
  }

  const row = {
    origen,
    destino,
    km: Number(body.km) || 0,
    costo_por_km: Number(body.costo_por_km) || 0,
    enabled: body.enabled !== false,
    updated_at: new Date().toISOString()
  };

  const response = await fetch(`${url}/rest/v1/${TABLE}?on_conflict=origen,destino`, {
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
