import { NextResponse } from "next/server";

// Metricas de ejecucion de los procesos del pipeline (desempeño, calidad y
// costo). Alimenta el grafo de la pestaña IA.
//
// La tabla guarda un agregado DIARIO por proceso; aqui se colapsa a un resumen
// por proceso sobre la ventana, para que el cliente no tenga que agregar nada.
//
// Hoy los datos son ficticios (supabase/seed-metrics.sql). Cuando se instrumente
// el codigo real solo cambia quien escribe las filas: este endpoint y la UI
// siguen igual.

const TABLE = "inventario_mp_app_process_metrics";

const SELECT = "proceso,fecha,ejecuciones,exitos,duracion_p50_ms,duracion_p95_ms,costo_usd,tokens_in,tokens_out";

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  return { url, key, ready: Boolean(url && key) };
}

const MISSING_MESSAGE =
  "Configura SUPABASE_URL y la llave secreta (SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY) para ver las métricas de los procesos.";

type Fila = {
  proceso: string;
  fecha: string;
  ejecuciones: number | string;
  exitos: number | string;
  duracion_p50_ms: number | string;
  duracion_p95_ms: number | string;
  costo_usd: number | string;
  tokens_in: number | string;
  tokens_out: number | string;
};

export type ProcessMetrics = {
  proceso: string;
  dias: number;
  ejecuciones: number;
  exitoPct: number;
  p50Ms: number;
  p95Ms: number;
  costoTotal: number;
  costoPorCorrida: number;
  tokensIn: number;
  tokensOut: number;
  // Serie diaria de ejecuciones, para dibujar tendencia si hace falta.
  serie: Array<{ fecha: string; ejecuciones: number }>;
};

function num(value: unknown) {
  return Number(value) || 0;
}

export async function GET() {
  const { url, key, ready } = config();
  if (!ready) {
    return NextResponse.json({ ok: false, message: MISSING_MESSAGE, metrics: [] });
  }

  const response = await fetch(`${url}/rest/v1/${TABLE}?select=${SELECT}&order=fecha.asc`, {
    headers: { apikey: key!, Authorization: `Bearer ${key!}` },
    cache: "no-store"
  });

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json({ ok: false, message: `Supabase ${response.status}: ${detail}`, metrics: [] });
  }

  const filas = (await response.json()) as Fila[];
  const porProceso = new Map<string, ProcessMetrics & { p50Suma: number }>();

  for (const fila of filas) {
    const actual = porProceso.get(fila.proceso) ?? {
      proceso: fila.proceso,
      dias: 0,
      ejecuciones: 0,
      exitoPct: 0,
      p50Ms: 0,
      p95Ms: 0,
      costoTotal: 0,
      costoPorCorrida: 0,
      tokensIn: 0,
      tokensOut: 0,
      serie: [],
      p50Suma: 0
    };

    const ejecuciones = num(fila.ejecuciones);
    actual.dias += 1;
    actual.ejecuciones += ejecuciones;
    // exitoPct acumula exitos y se convierte a porcentaje al final.
    actual.exitoPct += num(fila.exitos);
    actual.p50Suma += num(fila.duracion_p50_ms);
    // El p95 de la ventana NO es el promedio de los p95 diarios: se toma el
    // peor dia, que es la lectura conservadora y la unica derivable de un
    // agregado diario.
    actual.p95Ms = Math.max(actual.p95Ms, num(fila.duracion_p95_ms));
    actual.costoTotal += num(fila.costo_usd);
    actual.tokensIn += num(fila.tokens_in);
    actual.tokensOut += num(fila.tokens_out);
    actual.serie.push({ fecha: String(fila.fecha).slice(0, 10), ejecuciones });

    porProceso.set(fila.proceso, actual);
  }

  const metrics: ProcessMetrics[] = Array.from(porProceso.values()).map((item) => {
    const { p50Suma, ...resto } = item;
    return {
      ...resto,
      exitoPct: item.ejecuciones > 0 ? (item.exitoPct / item.ejecuciones) * 100 : 0,
      p50Ms: item.dias > 0 ? Math.round(p50Suma / item.dias) : 0,
      costoPorCorrida: item.ejecuciones > 0 ? item.costoTotal / item.ejecuciones : 0
    };
  });

  const costoTotal = metrics.reduce((total, item) => total + item.costoTotal, 0);
  const ejecuciones = metrics.reduce((total, item) => total + item.ejecuciones, 0);

  return NextResponse.json({ ok: true, metrics, costoTotal, ejecuciones, dias: 30 });
}
