import solver from "javascript-lp-solver";
import {
  DistributionPlan,
  DistributionStop,
  FleetInput,
  InventoryRow,
  Recommendation,
  RouteCost,
  Station
} from "./types";

const refineryName = "DANEC SANGOLQUI";

// Pesos del objetivo "acidez manda, costo real":
const BASE = 1; // por tonelada: incentiva LLENAR la recepcion (evita horas extra fin de semana)
const URGENT_BONUS = 1000; // por tonelada de fuente en el top 25% de acidez -> se despacha primero
const ACID_W = 10; // ordena entre si a las fuentes urgentes
const COST_W = 0.01; // peso REAL del costo: decide que NO urgente entra (ruta mas barata)

const sourceTypes = new Set(["EXTRACTORA", "PUERTO"]);

// Semillas por keyword para crear las 3 estaciones iniciales cuando no hay nada
// guardado. Las estaciones reales son configurables (productos asignados a mano).
const SEED_STATIONS: { nombre: string; test: RegExp }[] = [
  { nombre: "Estación 1", test: /HIBRIDO|ROJO DE PALMA|ESTEARINA/ },
  { nombre: "Estación 2", test: /SOYA|CANOLA|GIRASOL|MA[IÍ]Z/ },
  { nombre: "Estación 3", test: /PKO|PALMISTE/ }
];

// Estaciones por defecto: 3 estaciones (5 tanqueros c/u) con los productos del
// inventario asignados por keyword. Solo se usa si Supabase/localStorage vacios.
export function defaultStationSeed(products: string[]): Station[] {
  return SEED_STATIONS.map((seed, index) => ({
    id: `estacion-${index + 1}`,
    nombre: seed.nombre,
    tankers: 5,
    productos: products.filter((producto) => seed.test.test(producto.toUpperCase()))
  }));
}

// Mapa producto (normalizado) -> estacion que lo recibe. Producto sin estacion no
// puede recibirse y queda fuera del plan.
function buildProductStationMap(stations: Station[]) {
  const map = new Map<string, Station>();
  for (const station of stations) {
    for (const producto of station.productos) {
      map.set(normalize(producto), station);
    }
  }
  return map;
}

export type DistributionOptions = {
  enabledSources?: Set<string>;
  routeCost?: (origen: string, destino: string) => number;
  stations?: Station[];
};

type Source = {
  row: InventoryRow;
  occupancy: number;
  costPerTrip: number;
  station: Station;
  urgent: boolean;
};

// Plan de distribucion diario (MILP, javascript-lp-solver). El cuello de botella es
// la CAPACIDAD DE RECEPCION de la refineria: 3 estaciones, cada una recibe solo
// ciertos productos y un cupo de tanqueros/dia. El plan LLENA la recepcion (para
// explotarla entre semana) priorizando la acidez alta (top 25%) y minimizando costo,
// sin exceder el almacenamiento libre de la refineria.
export function buildDistributionPlan(
  rows: InventoryRow[],
  fleet: FleetInput,
  options: DistributionOptions = {}
): DistributionPlan {
  const { enabledSources, routeCost, stations = [] } = options;
  const dailyCapacity = fleet.unidades * fleet.toneladasPorUnidad * fleet.viajesPorDia;
  const truckCap = fleet.toneladasPorUnidad > 0 ? fleet.toneladasPorUnidad : 1;
  const tripsPerTruck = fleet.viajesPorDia > 0 ? fleet.viajesPorDia : 1;
  const productStation = buildProductStationMap(stations);

  const candidates = rows.filter(
    (row) =>
      sourceTypes.has(normalize(row.tipo)) &&
      row.disponible > 0 &&
      (!enabledSources || enabledSources.has(row.nombre)) &&
      productStation.has(normalize(row.producto))
  );

  const empty: DistributionPlan = {
    stops: [],
    toneladasTotales: 0,
    camionesUsados: 0,
    viajesTotales: 0,
    capacidadDiaria: dailyCapacity,
    costoTotal: 0
  };
  if (candidates.length === 0) return empty;

  // Acidez "urgente" = top 25% (percentil 75) de las fuentes del dia.
  const p75 = percentile(candidates.map((row) => row.acidez), 0.75);

  const sources: Source[] = candidates.map((row) => ({
    row,
    occupancy: row.capacidad > 0 ? row.disponible / row.capacidad : 0,
    costPerTrip: routeCost ? Math.max(0, routeCost(row.nombre, refineryName)) : 0,
    station: productStation.get(normalize(row.producto))!,
    urgent: row.acidez >= p75
  }));

  const refineryFree = getRefineryFreeCapacity(rows).byProduct;
  const products = Array.from(new Set(sources.map((source) => source.row.producto)));

  const solved = solvePlan(sources, products, stations, { refineryFree, truckCap });
  if (!solved || !solved.feasible) return empty;

  const stops: DistributionStop[] = [];
  sources.forEach((source, index) => {
    const trips = Math.round(Number(solved[`trips_${index}`] ?? 0));
    const toneladas = Math.round(Number(solved[`tons_${index}`] ?? 0));
    if (trips <= 0 || toneladas <= 0) return;
    const camiones = Math.ceil(trips / tripsPerTruck);
    const viajesPorCamion = Math.ceil(trips / camiones);
    stops.push({
      origen: source.row.nombre,
      producto: source.row.producto,
      tanque: source.row.tanque,
      estacion: source.station.nombre,
      occupancy: source.occupancy,
      acidez: source.row.acidez,
      urgency: source.row.acidez,
      toneladas,
      camiones,
      viajesPorCamion,
      costo: Math.round(source.costPerTrip * trips)
    });
  });
  // Por estacion y luego mayor acidez para lectura.
  stops.sort(
    (a, b) => a.estacion.localeCompare(b.estacion) || b.acidez - a.acidez || b.toneladas - a.toneladas
  );

  return {
    stops,
    toneladasTotales: stops.reduce((total, stop) => total + stop.toneladas, 0),
    camionesUsados: stops.reduce((total, stop) => total + stop.camiones, 0),
    viajesTotales: stops.reduce((total, stop) => total + stop.camiones * stop.viajesPorCamion, 0),
    capacidadDiaria: dailyCapacity,
    costoTotal: stops.reduce((total, stop) => total + stop.costo, 0)
  };
}

type SolveParams = {
  refineryFree: Record<string, number>;
  truckCap: number;
};

// MILP "acidez manda, costo real": maximiza Σ w·tons − COST_W·Σ costPorViaje·viajes.
// Los urgentes (top 25% acidez) llevan un bono enorme y entran primero; los NO
// urgentes solo aportan BASE·tons, asi que entre ellos decide el costo de ruta.
// Topes: disponible por fuente, almacenamiento libre por producto y cupo de
// tanqueros por estacion (el limite real de recepcion).
function solvePlan(sources: Source[], products: string[], stations: Station[], params: SolveParams) {
  const { refineryFree, truckCap } = params;
  const variables: Record<string, Record<string, number>> = {};
  const ints: Record<string, 1> = {};
  const constraints: Record<string, { min?: number; max?: number }> = {};

  for (const station of stations) {
    constraints[`station_${station.id}`] = { max: Math.max(0, station.tankers) };
  }

  for (const p of products) {
    constraints[`refcap_${p}`] = { max: refineryFree[p] ?? 0 };
  }

  sources.forEach((source, index) => {
    const p = source.row.producto;
    // Sin acidez para los NO urgentes -> compiten solo por costo de ruta.
    const weight = BASE + (source.urgent ? URGENT_BONUS + ACID_W * source.row.acidez : 0);
    variables[`tons_${index}`] = {
      cost: weight,
      [`cap_${index}`]: 1,
      [`link_${index}`]: 1,
      [`refcap_${p}`]: 1
    };
    variables[`trips_${index}`] = {
      cost: -COST_W * source.costPerTrip,
      [`link_${index}`]: -truckCap,
      [`station_${source.station.id}`]: 1
    };
    constraints[`cap_${index}`] = { max: source.row.disponible };
    constraints[`link_${index}`] = { max: 0 };
    ints[`trips_${index}`] = 1;
  });

  const model = {
    optimize: "cost",
    opType: "max" as const,
    constraints,
    variables,
    ints
  };

  try {
    return solver.Solve(model) as unknown as { feasible: boolean; [key: string]: number | boolean };
  } catch {
    return null;
  }
}

// Percentil (0..1) de una lista de numeros (interpolacion lineal). 0 si vacia.
function percentile(values: number[], q: number) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const lower = Math.floor(pos);
  const upper = Math.ceil(pos);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (pos - lower);
}

// Capacidad libre por producto (suma de cap - disponible) de las filas que pasan
// el filtro. Reutilizable para refineria y puerto.
function freeCapacity(rows: InventoryRow[], keep: (row: InventoryRow) => boolean) {
  const byProduct: Record<string, number> = {};
  let total = 0;
  for (const row of rows) {
    if (row.capacidad <= 0 || !keep(row)) continue;
    const free = Math.max(0, row.capacidad - row.disponible);
    byProduct[row.producto] = (byProduct[row.producto] ?? 0) + free;
    total += free;
  }
  return { total, byProduct };
}

// Capacidad libre de la refineria (DANEC) por producto. Valida que los despachos
// no excedan el espacio de la refineria.
export function getRefineryFreeCapacity(rows: InventoryRow[]) {
  return freeCapacity(rows, (row) => normalize(row.nombre) === normalize(refineryName));
}

// Capacidad libre del PUERTO por producto. Su almacenaje puede recibir transitos.
export function getPuertoFreeCapacity(rows: InventoryRow[]) {
  return freeCapacity(rows, (row) => normalize(row.tipo) === "PUERTO");
}

// Material entrante por producto: proveedores (pendienteRetiro), importaciones y
// transito (filas sin tanque). Necesita espacio donde almacenarse.
export function getIncomingByProduct(rows: InventoryRow[]) {
  const byProduct: Record<string, number> = {};
  let total = 0;
  for (const row of rows) {
    if (row.tanque) continue;
    const incoming = row.transito + row.importaciones + row.pendienteRetiro;
    if (incoming <= 0) continue;
    byProduct[row.producto] = (byProduct[row.producto] ?? 0) + incoming;
    total += incoming;
  }
  return { total, byProduct };
}

// Estado de cada extractora (ocupacion y acidez) para que la IA evalue calidad y
// espacio disponible para el material entrante.
export function getExtractoraStatus(rows: InventoryRow[]) {
  return rows
    .filter((row) => normalize(row.tipo) === "EXTRACTORA")
    .map((row) => ({
      nombre: row.nombre,
      producto: row.producto,
      tanque: row.tanque,
      capacidad: row.capacidad,
      disponible: row.disponible,
      libre: Math.max(0, row.capacidad - row.disponible),
      occupancy: row.capacidad > 0 ? Number((row.disponible / row.capacidad).toFixed(3)) : 0,
      acidez: row.acidez
    }))
    .sort((a, b) => b.acidez - a.acidez || b.occupancy - a.occupancy);
}

export function getKpis(rows: InventoryRow[]) {
  const totalCapacity = sum(rows.map((row) => row.capacidad));
  const totalNetInventory = sum(rows.map((row) => row.disponible));
  const committedFuture = sum(rows.map((row) => row.transito + row.importaciones));
  // La acidez (% de acidos grasos libres) solo se mide en las extractoras; el
  // resto de tipos no reporta el dato, asi que se pondera solo sobre ellas.
  const extractoraRows = rows.filter((row) => normalize(row.tipo) === "EXTRACTORA");
  const extractoraInventory = sum(extractoraRows.map((row) => row.disponible));
  const weightedAcidity =
    extractoraInventory > 0
      ? sum(extractoraRows.map((row) => row.disponible * row.acidez)) / extractoraInventory
      : 0;

  return {
    totalCapacity,
    totalNetInventory,
    occupancy: totalCapacity > 0 ? totalNetInventory / totalCapacity : 0,
    committedFuture,
    weightedAcidity
  };
}

export function buildRecommendations(
  rows: InventoryRow[],
  routes: RouteCost[],
  fleet: FleetInput
): Recommendation[] {
  const refineryRows = rows.filter((row) => normalize(row.nombre) === normalize(refineryName));
  const refineryDemand = Math.max(
    0,
    sum(refineryRows.map((row) => row.pedido - row.retirado + row.pendienteRetiro)) -
      sum(refineryRows.map((row) => row.transito))
  );
  const dailyFleetCapacity = fleet.unidades * fleet.toneladasPorUnidad * fleet.viajesPorDia;
  const targetMove = Math.min(refineryDemand || dailyFleetCapacity, dailyFleetCapacity);

  return rows
    .filter((row) => normalize(row.nombre) !== normalize(refineryName) && row.disponible > 0)
    .map((row): Recommendation => {
      const route = routes.find(
        (candidate) =>
          normalize(candidate.origen) === normalize(row.nombre) &&
          normalize(candidate.destino) === normalize(refineryName)
      );
      const routeCost = route ? route.km * route.costoPorKm : 9999;
      const acidityPenalty = Math.max(0, row.acidez - 3) * 18;
      const urgency = row.diasRetrazo * 22 + occupancyPressure(row) + row.pendienteRetiro * 0.03;
      const logisticsScore = Math.max(0, 100 - routeCost / 8 - acidityPenalty + urgency);
      const suggestedTons = Math.max(
        0,
        Math.min(row.disponible * 0.35, targetMove, row.pendienteRetiro || row.disponible * 0.2)
      );
      const priority: Recommendation["priority"] =
        logisticsScore > 78 ? "alta" : logisticsScore > 48 ? "media" : "baja";

      return {
        id: `${row.nombre}-${row.tanque}-${row.producto}`,
        priority,
        title: `${row.nombre} -> ${refineryName}`,
        detail: buildDetail(row, routeCost, suggestedTons),
        suggestedTons: Math.round(suggestedTons),
        source: row.nombre,
        product: row.producto,
        acidPenalty: Math.round(acidityPenalty),
        logisticsScore: Math.round(logisticsScore)
      };
    })
    .sort((a, b) => b.logisticsScore - a.logisticsScore);
}

function buildDetail(row: InventoryRow, routeCost: number, suggestedTons: number) {
  const cost = routeCost === 9999 ? "ruta pendiente" : `$${routeCost.toFixed(0)} por viaje base`;
  return `${row.producto} en ${row.tanque}. Acidez ${row.acidez.toFixed(
    1
  )}, inventario neto ${row.disponible.toLocaleString("es-EC")} t, costo referencial ${cost}. Movimiento sugerido ${Math.round(
    suggestedTons
  ).toLocaleString("es-EC")} t.`;
}

function occupancyPressure(row: InventoryRow) {
  if (row.capacidad <= 0) return 0;
  const occupancy = row.disponible / row.capacidad;
  if (occupancy > 0.9) return 28;
  if (occupancy > 0.75) return 14;
  if (occupancy < 0.25) return -16;
  return 0;
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function normalize(value: string) {
  return value.trim().toUpperCase();
}
