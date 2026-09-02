import { NextResponse } from "next/server";

// Persiste y consulta las estaciones de recepcion configurables (nombre, cupo de
// tanqueros/dia y productos asignados) en Supabase. Usa la llave secreta SOLO en
// el servidor. Degrada con ok:false si faltan variables, igual que /api/routes.

const TABLE = "inventario_mp_app_stations";

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para guardar las estaciones de recepción.";

// GET: devuelve las estaciones guardadas, ordenadas por posicion.
export async function GET() {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, stations: [] });
  }

  const response = await fetch(
    `${url}/rest/v1/${TABLE}?select=id,nombre,tankers,productos,posicion&order=posicion.asc`,
    { headers: { apikey: key!, Authorization: `Bearer ${key!}` }, cache: "no-store" }
  );

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, stations: [] });
  }

  const stations = await response.json();
  return NextResponse.json({ ok: true, stations });
}

// POST: recibe el arreglo COMPLETO de estaciones. Hace upsert de cada una
// (on_conflict=id) y elimina de la tabla las ids que ya no estan en el arreglo.
export async function POST(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE });
  }

  const body = await request.json();
  const incoming = Array.isArray(body.stations) ? body.stations : [];

  const rows = incoming.map((station: Record<string, unknown>, index: number) => ({
    id: String(station.id ?? "").trim(),
    nombre: String(station.nombre ?? "Estación").trim() || "Estación",
    tankers: Number(station.tankers) || 0,
    productos: Array.isArray(station.productos) ? station.productos.map(String) : [],
    posicion: index,
    updated_at: new Date().toISOString()
  })).filter((row: { id: string }) => row.id);

  const headers = {
    apikey: key!,
    Authorization: `Bearer ${key!}`,
    "Content-Type": "application/json"
  };

  // 1) Borra las estaciones que ya no existen (todas si el arreglo viene vacio).
  const keepIds = rows.map((row: { id: string }) => row.id);
  const deleteFilter = keepIds.length
    ? `id=not.in.(${keepIds.map((id: string) => `"${id}"`).join(",")})`
    : "id=not.is.null";
  const deleteResponse = await fetch(`${url}/rest/v1/${TABLE}?${deleteFilter}`, {
    method: "DELETE",
    headers: { ...headers, Prefer: "return=minimal" }
  });
  if (!deleteResponse.ok) {
    const detail = await deleteResponse.text();
    return NextResponse.json({ ok: false, message: `Supabase ${deleteResponse.status}: ${detail}` });
  }

  // 2) Upsert de las estaciones actuales.
  if (rows.length > 0) {
    const upsertResponse = await fetch(`${url}/rest/v1/${TABLE}?on_conflict=id`, {
      method: "POST",
      headers: { ...headers, Prefer: "resolution=merge-duplicates,return=minimal" },
      body: JSON.stringify(rows)
    });
    if (!upsertResponse.ok) {
      const detail = await upsertResponse.text();
      return NextResponse.json({ ok: false, message: `Supabase ${upsertResponse.status}: ${detail}` });
    }
  }

  return NextResponse.json({ ok: true, count: rows.length });
}
