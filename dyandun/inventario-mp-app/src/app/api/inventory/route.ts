import { NextResponse } from "next/server";
import { InventoryRow } from "@/lib/types";

// Lee los snapshots diarios de inventario persistidos en Supabase. Es la UNICA
// fuente de inventario real de la app: sin filas aca, la UI cae al mock de
// sample-data.ts (3 fechas) y el historico queda sin forma.
// Usa la llave secreta SOLO en el servidor. Degrada con ok:false si faltan
// variables, igual que /api/plan, /api/routes y /api/stations.

const TABLE = "inventario_mp_app_inventory";

const SELECT = [
  "fecha",
  "tipo",
  "nombre",
  "producto",
  "tanque",
  "capacidad",
  "inventario",
  "disponible",
  "acidez",
  "oc",
  "orden_recibida_en_bodega",
  "fecha_orden",
  "dias_retrazo",
  "pedido",
  "retirado",
  "pendiente_retiro",
  "observacion",
  "transito",
  "importaciones"
].join(",");

// Orden estable (fecha + desempate) para que la paginacion por Range no repita
// ni saltee filas entre paginas.
const ORDER = "order=fecha.asc,nombre.asc,producto.asc,tanque.asc";

// Supabase limita las respuestas de PostgREST (db-max-rows, 1000 por defecto),
// asi que se pagina con el header Range en vez de confiar en una sola llamada.
const PAGE_SIZE = 1000;
const MAX_PAGES = 20; // tope de seguridad: 20.000 filas

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para leer el histórico de inventario.";

type Row = Record<string, unknown>;

function num(value: unknown) {
  return Number(value) || 0;
}

function text(value: unknown) {
  return value == null ? "" : String(value);
}

// Los campos opcionales de InventoryRow se omiten si vienen null, para no
// llenar la UI de cadenas vacias donde antes no habia nada.
function optional(value: unknown) {
  return value == null || value === "" ? undefined : String(value);
}

function toInventoryRow(row: Row): InventoryRow {
  return {
    fecha: text(row.fecha),
    tipo: text(row.tipo),
    nombre: text(row.nombre),
    producto: text(row.producto),
    tanque: text(row.tanque),
    capacidad: num(row.capacidad),
    inventario: num(row.inventario),
    disponible: num(row.disponible),
    acidez: num(row.acidez),
    oc: optional(row.oc),
    ordenRecibidaEnBodega: optional(row.orden_recibida_en_bodega),
    fechaOrden: optional(row.fecha_orden),
    diasRetrazo: num(row.dias_retrazo),
    pedido: num(row.pedido),
    retirado: num(row.retirado),
    pendienteRetiro: num(row.pendiente_retiro),
    observacion: optional(row.observacion),
    transito: num(row.transito),
    importaciones: num(row.importaciones)
  };
}

// GET: devuelve todos los snapshots, ordenados por fecha ascendente.
export async function GET() {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, rows: [] });
  }

  const rows: InventoryRow[] = [];

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const from = page * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    const response = await fetch(`${url}/rest/v1/${TABLE}?select=${SELECT}&${ORDER}`, {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key!}`,
        Range: `${from}-${to}`
      },
      cache: "no-store"
    });

    if (!response.ok) {
      const detail = await response.text();
      return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, rows: [] });
    }

    const batch = (await response.json()) as Row[];
    rows.push(...batch.map(toInventoryRow));

    // Pagina incompleta = no hay mas filas.
    if (batch.length < PAGE_SIZE) break;
  }

  const fechas = new Set(rows.map((row) => row.fecha));
  return NextResponse.json({ ok: true, rows, registros: rows.length, fechas: fechas.size });
}
