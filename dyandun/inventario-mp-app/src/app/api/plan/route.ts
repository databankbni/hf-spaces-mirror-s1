import { NextResponse } from "next/server";

// Persiste y consulta los planes de distribucion aprobados en Supabase.
// Usa el service_role key SOLO en el servidor (nunca se expone al cliente).
// Si faltan las variables responde ok:false con un mensaje, igual que las otras
// rutas (telegram/email), para no romper la app sin configurar.

const TABLE = "inventario_mp_app_approved_dispatches";

function config() {
  const url = process.env.SUPABASE_URL;
  // Acepta la llave secreta de servidor en cualquier formato/nombre: la
  // service_role clasica (JWT) o la nueva secret key (sb_secret_...). Ambas
  // sirven como apikey/Bearer en PostgREST y saltan RLS. NO usar la
  // publishable/anon aqui (respeta RLS y no podria insertar).
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para guardar y acumular planes aprobados.";

// Supabase corta las respuestas de PostgREST en db-max-rows (1000 por defecto).
// El acumulado y el grafico necesitan TODAS las filas, asi que se pagina con el
// header Range. Sin esto el KPI queda truncado en silencio, y como PostgREST
// sin `order` no garantiza cual subconjunto devuelve, el recorte seria arbitrario.
const PAGE_SIZE = 1000;
const MAX_PAGES = 50; // tope de seguridad: 50.000 despachos
const ORDER = "order=fecha.asc,id.asc";

// GET: devuelve el acumulado de toneladas transportadas (suma de la tabla).
export async function GET() {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, totalTransportado: null });
  }

  type Row = {
    fecha?: string;
    toneladas: number | string;
    camiones?: number | string;
    costo?: number | string;
  };

  const rows: Row[] = [];

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const from = page * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    const response = await fetch(`${url}/rest/v1/${TABLE}?select=fecha,toneladas,camiones,costo&${ORDER}`, {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key!}`,
        Range: `${from}-${to}`
      },
      cache: "no-store"
    });

    if (!response.ok) {
      const detail = await response.text();
      return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, totalTransportado: null });
    }

    const batch = (await response.json()) as Row[];
    rows.push(...batch);

    // Pagina incompleta = no hay mas filas.
    if (batch.length < PAGE_SIZE) break;
  }

  const totalTransportado = rows.reduce((total, row) => total + (Number(row.toneladas) || 0), 0);

  // Agregado por fecha: camiones, costo y toneladas (para el grafico historico).
  const byDate = new Map<string, { fecha: string; camiones: number; costo: number; toneladas: number }>();
  for (const row of rows) {
    const fecha = String(row.fecha ?? "").slice(0, 10);
    if (!fecha) continue;
    const current = byDate.get(fecha) ?? { fecha, camiones: 0, costo: 0, toneladas: 0 };
    current.camiones += Number(row.camiones) || 0;
    current.costo += Number(row.costo) || 0;
    current.toneladas += Number(row.toneladas) || 0;
    byDate.set(fecha, current);
  }
  const daily = Array.from(byDate.values()).sort((a, b) => a.fecha.localeCompare(b.fecha));

  // Plan aprobado de HOY, para que la tarjeta se rehidrate al recargar la
  // pagina. Sin esto el estado "aprobado" vivia solo en memoria del navegador y
  // un refresco permitia volver a aprobar el mismo plan, duplicandolo.
  const todayPlan = await readTodayPlan(url!, key!);

  return NextResponse.json({ ok: true, totalTransportado, registros: rows.length, daily, todayPlan });
}

type StoredStop = {
  plan_id: string;
  partida: string;
  destino: string;
  producto: string;
  tanque: string | null;
  toneladas: number | string;
  camiones: number | string;
  viajes_por_camion: number | string;
  costo: number | string;
  occupancy: number | string | null;
  acidez: number | string | null;
};

// Devuelve el ULTIMO plan aprobado hoy con todas sus filas. Si en el dia se
// aprobo mas de un plan, gana el mas reciente por approved_at: es el que la
// tarjeta debe mostrar como vigente.
async function readTodayPlan(url: string, key: string) {
  const hoy = new Date().toISOString().slice(0, 10);
  const select = "plan_id,partida,destino,producto,tanque,toneladas,camiones,viajes_por_camion,costo,occupancy,acidez";

  const response = await fetch(
    `${url}/rest/v1/${TABLE}?select=${select}&fecha=eq.${hoy}&order=approved_at.desc,id.asc`,
    {
      headers: { apikey: key, Authorization: `Bearer ${key}` },
      cache: "no-store"
    }
  );

  // El acumulado no debe caerse porque falle esta consulta secundaria.
  if (!response.ok) return null;

  const rows = (await response.json().catch(() => [])) as StoredStop[];
  if (!Array.isArray(rows) || rows.length === 0) return null;

  const planId = rows[0].plan_id;
  const stops = rows
    .filter((row) => row.plan_id === planId)
    .map((row) => ({
      partida: String(row.partida ?? ""),
      destino: String(row.destino ?? ""),
      producto: String(row.producto ?? ""),
      tanque: String(row.tanque ?? ""),
      toneladas: Number(row.toneladas) || 0,
      camiones: Number(row.camiones) || 0,
      viajesPorCamion: Number(row.viajes_por_camion) || 1,
      costo: Number(row.costo) || 0,
      occupancy: Number(row.occupancy) || 0,
      acidez: Number(row.acidez) || 0
    }));

  return { planId, stops };
}

// Borra todas las filas de un plan. Se usa tanto para "Eliminar" como para el
// reemplazo que hace la edicion de un plan ya aprobado.
async function deletePlan(url: string, key: string, planId: string) {
  return fetch(`${url}/rest/v1/${TABLE}?plan_id=eq.${encodeURIComponent(planId)}`, {
    method: "DELETE",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      Prefer: "return=representation"
    },
    cache: "no-store"
  });
}

// POST: inserta los stops aprobados del plan diario.
//
// Con `replacePlanId` sustituye un plan ya aprobado (editar). El orden importa:
// se INSERTA primero y solo despues se borra el anterior. Al reves, un fallo en
// el insert dejaria al usuario sin el plan que ya tenia guardado; asi el peor
// caso es que queden las dos versiones, algo visible y reparable.
export async function POST(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE });
  }

  const body = await request.json();
  const stops = Array.isArray(body.stops) ? body.stops : [];
  const replacePlanId = typeof body.replacePlanId === "string" ? body.replacePlanId : "";
  if (stops.length === 0) {
    return NextResponse.json({ ok: false, message: "No hay despachos para aprobar." });
  }

  const response = await fetch(`${url}/rest/v1/${TABLE}`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key!}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal"
    },
    body: JSON.stringify(stops)
  });

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}` });
  }

  const toneladas = stops.reduce((total: number, stop: { toneladas?: number | string }) => total + (Number(stop.toneladas) || 0), 0);

  if (replacePlanId) {
    const cleanup = await deletePlan(url!, key!, replacePlanId);
    if (!cleanup.ok) {
      const detail = await cleanup.text();
      // La version nueva SI quedo guardada: hay que decirlo para que el
      // acumulado inflado no se lea como un error de calculo.
      return NextResponse.json({
        ok: true,
        registros: stops.length,
        toneladas,
        warning: `Se guardó la versión nueva, pero no se pudo borrar la anterior (Supabase ${cleanup.status}: ${detail}). El plan quedó duplicado en la base.`
      });
    }
  }

  return NextResponse.json({ ok: true, registros: stops.length, toneladas });
}

// DELETE: elimina un plan aprobado completo (todas las filas con ese plan_id).
export async function DELETE(request: Request) {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE });
  }

  const body = await request.json().catch(() => null);
  const planId = typeof body?.planId === "string" ? body.planId : "";
  if (!planId) {
    return NextResponse.json({ ok: false, message: "Falta el identificador del plan a eliminar." });
  }

  const response = await deletePlan(url!, key!, planId);

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}` });
  }

  const borradas = (await response.json().catch(() => [])) as unknown[];
  return NextResponse.json({ ok: true, registros: Array.isArray(borradas) ? borradas.length : 0 });
}
