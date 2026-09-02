"use client";

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Gauge,
  LineChart,
  Mail,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Save,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Truck,
  X
} from "lucide-react";
import type { ReactNode } from "react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildDistributionPlan,
  buildRecommendations,
  defaultStationSeed,
  getExtractoraStatus,
  getIncomingByProduct,
  getKpis,
  getPuertoFreeCapacity,
  getRefineryFreeCapacity
} from "@/lib/optimizer";
import { sampleInventory, sampleRoutes } from "@/lib/sample-data";
import type { ProcessMetrics } from "@/app/api/metrics/route";
import { DistributionPlan, DistributionStop, FleetInput, InventoryRow, RouteCost, Station } from "@/lib/types";

type View = "inventario" | "datos" | "rutas" | "ia";

type DailyApproved = { fecha: string; camiones: number; costo: number; toneladas: number };

// Plan aprobado tal como quedo guardado en Supabase (lo devuelve /api/plan).
// Es la version que manda al recargar la pagina: la tarjeta se rehidrata con
// estas filas, no con lo que acabe de calcular el optimizador.
type StoredStop = {
  partida: string;
  destino: string;
  producto: string;
  tanque: string;
  toneladas: number;
  camiones: number;
  viajesPorCamion: number;
  costo: number;
  occupancy: number;
  acidez: number;
};

type StoredPlan = { planId: string; stops: StoredStop[] };

// Procedencia del inventario en pantalla. "supabase" = snapshots persistidos
// (fuente real y compartida); "demo" = mock de sample-data.ts, que solo aparece
// si Supabase no responde o esta vacia.
type DataSource = "demo" | "supabase";

// Granularidad de las vistas temporales del inventario (historico + heatmap).
// "diario" = ultimos DAILY_WINDOW dias; "mensual" = meses del anio en curso.
type Granularity = "diario" | "mensual";

// Ventana fija del modo diario. En mensual la ventana es el anio completo.
const DAILY_WINDOW = 30;

const refineryName = "DANEC SANGOLQUI";

export default function Home() {
  const [rows, setRows] = useState<InventoryRow[]>(sampleInventory);
  const [dataSource, setDataSource] = useState<DataSource>("demo");
  const [fleet, setFleet] = useState<FleetInput>({
    unidades: 65,
    toneladasPorUnidad: 32,
    viajesPorDia: 1
  });
  const [fleetSaveStatus, setFleetSaveStatus] = useState("");
  const [navOpen, setNavOpen] = useState(true);
  const [view, setView] = useState<View>("inventario");
  const [product, setProduct] = useState("TODOS");
  const [granularity, setGranularity] = useState<Granularity>("diario");
  // Granularidad del grafico de rutas, independiente de la de inventario: son
  // dos pantallas distintas y cambiar una no deberia mover la otra.
  const [planGranularity, setPlanGranularity] = useState<Granularity>("diario");
  // Revision del plan por la IA. Alimenta las tarjetas que anotan cada fila del
  // plan y el veredicto adversarial. La dispara "Revisar con IA".
  const [planReview, setPlanReview] = useState("");
  const [loadingPlanReview, setLoadingPlanReview] = useState(false);
  // Chat del panel flotante: conversacion libre por temas. Es una funcion
  // distinta de la revision del plan, con su propio estado y su propia prosa.
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatTopic, setChatTopic] = useState("");
  const [loadingChat, setLoadingChat] = useState(false);
  // Metricas de desempeño, calidad y costo de cada proceso del pipeline.
  const [processMetrics, setProcessMetrics] = useState<ProcessMetrics[]>([]);
  // Acumulado real de toneladas transportadas (planes aprobados en Supabase).
  // null = Supabase no configurado/sin datos -> se usa el total del plan del dia.
  const [totalTransportado, setTotalTransportado] = useState<number | null>(null);
  // Histórico diario de planes aprobados (camiones y costo por fecha).
  const [dailyApproved, setDailyApproved] = useState<DailyApproved[]>([]);
  // Plan ya aprobado hoy en Supabase. Rehidrata la tarjeta al recargar: sin
  // esto el bloqueo vivia solo en memoria y un refresco dejaba volver a
  // aprobar el mismo plan.
  const [todayPlan, setTodayPlan] = useState<StoredPlan | null>(null);

  const refreshTransported = useCallback(async () => {
    try {
      const response = await fetch("/api/plan", { cache: "no-store" });
      const data = await response.json();
      setTotalTransportado(data.ok ? data.totalTransportado : null);
      setDailyApproved(data.ok && Array.isArray(data.daily) ? data.daily : []);
      setTodayPlan(data.ok && data.todayPlan ? (data.todayPlan as StoredPlan) : null);
    } catch {
      setTotalTransportado(null);
      setDailyApproved([]);
      setTodayPlan(null);
    }
  }, []);

  useEffect(() => {
    refreshTransported();
  }, [refreshTransported]);

  // Tarjetas del analisis IA, para anotar el plan de distribucion con el motivo
  // y el riesgo que la IA dio a cada despacho. El plan lo sigue decidiendo el
  // MILP; esto solo agrega el "por que".
  const priorityCards = useMemo(() => parseAiCards(planReview).cards, [planReview]);

  // Serie del grafico de rutas: en diario, los ultimos 30 dias con plan
  // aprobado (dailyApproved ya viene ordenado ascendente desde /api/plan).
  const approvedSeries = useMemo(
    () =>
      planGranularity === "mensual"
        ? toMonthlyApproved(dailyApproved)
        : dailyApproved.slice(-DAILY_WINDOW),
    [dailyApproved, planGranularity]
  );

  // Metricas del pipeline. Si Supabase no responde, el grafo se dibuja igual
  // pero sin numeros: son informativas, no bloquean nada.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/metrics", { cache: "no-store" });
        const data = await response.json();
        if (!cancelled && data.ok && Array.isArray(data.metrics)) setProcessMetrics(data.metrics);
      } catch {
        // sin metricas: el grafo funciona igual
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Inventario: unica fuente de datos reales. Si Supabase tiene snapshots,
  // reemplazan al mock demo (que solo trae 3 fechas). Si no responde o esta
  // vacia, se queda el mock y el badge sigue diciendo "Datos demo".
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/inventory", { cache: "no-store" });
        const data = await response.json();
        if (cancelled) return;
        if (data.ok && Array.isArray(data.rows) && data.rows.length > 0) {
          setRows(data.rows);
          setDataSource("supabase");
        }
      } catch {
        // sin Supabase: se mantiene sampleInventory
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Flota: dato COMPARTIDO. Supabase es la fuente de verdad (todos ven lo mismo);
  // localStorage solo es respaldo si Supabase no responde y no pisa a Supabase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/settings?key=fleet", { cache: "no-store" });
        const data = await response.json();
        if (!cancelled && data.ok && data.value && typeof data.value === "object") {
          setFleet((prev) => ({
            unidades: Number(data.value.unidades) || prev.unidades,
            toneladasPorUnidad: Number(data.value.toneladasPorUnidad) || prev.toneladasPorUnidad,
            viajesPorDia: Number(data.value.viajesPorDia) || prev.viajesPorDia
          }));
          return; // gana Supabase
        }
      } catch {
        // sin Supabase
      }
      if (cancelled) return;
      try {
        const saved = localStorage.getItem("inventario_mp_app_fleet");
        if (saved) {
          const parsed = JSON.parse(saved);
          setFleet((prev) => ({
            unidades: Number(parsed.unidades) || prev.unidades,
            toneladasPorUnidad: Number(parsed.toneladasPorUnidad) || prev.toneladasPorUnidad,
            viajesPorDia: Number(parsed.viajesPorDia) || prev.viajesPorDia
          }));
        }
      } catch {
        // localStorage no disponible
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const saveFleet = useCallback(async () => {
    setFleetSaveStatus("Guardando…");
    try {
      localStorage.setItem("inventario_mp_app_fleet", JSON.stringify(fleet));
    } catch {
      // ignore
    }
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "fleet", value: fleet })
      });
      const data = await response.json();
      const hora = new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });
      if (data.ok) {
        setFleetSaveStatus(`Guardado con éxito a las ${hora}.`);
      } else {
        setFleetSaveStatus("Guardado local (configura Supabase para compartir entre usuarios).");
      }
      return true;
    } catch {
      setFleetSaveStatus("Guardado local (sin conexión a Supabase).");
      return true;
    }
  }, [fleet]);

  // Matriz de rutas editable. routeOverrides guarda km/$/km/enabled por par
  // origen|||destino (sembrado del demo y luego mezclado con lo guardado en
  // Supabase). Las filas visibles se derivan de los nodos con tanque.
  const [routeOverrides, setRouteOverrides] = useState<Record<string, Partial<RouteCost>>>(() => {
    const seed: Record<string, Partial<RouteCost>> = {};
    for (const route of sampleRoutes) {
      seed[routeKey(route.origen, route.destino)] = {
        km: route.km,
        costoPorKm: route.costoPorKm,
        enabled: true
      };
    }
    return seed;
  });

  const refreshRoutes = useCallback(async () => {
    try {
      const response = await fetch("/api/routes", { cache: "no-store" });
      const data = await response.json();
      if (!data.ok || !Array.isArray(data.routes)) return;
      setRouteOverrides((prev) => {
        const next = { ...prev };
        for (const row of data.routes) {
          next[routeKey(row.origen, row.destino)] = {
            km: Number(row.km) || 0,
            costoPorKm: Number(row.costo_por_km) || 0,
            enabled: row.enabled !== false
          };
        }
        return next;
      });
    } catch {
      // Sin Supabase: la matriz funciona en memoria.
    }
  }, []);

  useEffect(() => {
    refreshRoutes();
  }, [refreshRoutes]);

  // Nodos de la matriz: ubicaciones con tanque (extractoras, puerto, refineria) y
  // los PROVEEDORES (suministro sin tanque). nombre -> tipo normalizado.
  const matrixNodes = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of rows) {
      const tipo = normalize(row.tipo);
      if (["EXTRACTORA", "PUERTO", "REFINERIA", "PROVEEDORES"].includes(tipo) && row.nombre && !map.has(row.nombre)) {
        map.set(row.nombre, tipo);
      }
    }
    return map;
  }, [rows]);

  // Matriz de pares dirigidos origen->destino (origen != destino). Reglas por tipo:
  // - entre nodos con tanque (extractora/puerto/refineria): todas las combinaciones.
  // - PROVEEDORES: solo ENVIAN, y solo a extractoras y refineria (no a puerto ni
  //   entre proveedores); nunca son destino.
  const routes = useMemo<RouteCost[]>(() => {
    const list: RouteCost[] = [];
    const names = Array.from(matrixNodes.keys()).sort();
    for (const origen of names) {
      const origenTipo = matrixNodes.get(origen)!;
      for (const destino of names) {
        if (origen === destino) continue;
        const destinoTipo = matrixNodes.get(destino)!;
        if (destinoTipo === "PROVEEDORES") continue; // los proveedores no reciben
        if (origenTipo === "PROVEEDORES" && !["EXTRACTORA", "REFINERIA"].includes(destinoTipo)) continue;
        const override = routeOverrides[routeKey(origen, destino)];
        list.push({
          origen,
          destino,
          km: override?.km ?? 0,
          costoPorKm: override?.costoPorKm ?? 0,
          enabled: override?.enabled ?? true
        });
      }
    }
    return list;
  }, [matrixNodes, routeOverrides]);

  // Edits en memoria (el plan recalcula al vuelo). Persisten al pulsar "Guardar".
  const dirtyRoutes = useRef<Set<string>>(new Set());
  const [routesSaveStatus, setRoutesSaveStatus] = useState("");

  const updateRoute = useCallback((origen: string, destino: string, patch: Partial<RouteCost>) => {
    const key = routeKey(origen, destino);
    dirtyRoutes.current.add(key);
    setRoutesSaveStatus("Cambios sin guardar");
    setRouteOverrides((prev) => {
      const current = prev[key] ?? {};
      const merged: Partial<RouteCost> = {
        km: current.km ?? 0,
        costoPorKm: current.costoPorKm ?? 0,
        enabled: current.enabled ?? true,
        ...patch
      };
      return { ...prev, [key]: merged };
    });
  }, []);

  const saveRoutes = useCallback(async () => {
    const keys = Array.from(dirtyRoutes.current);
    if (keys.length === 0) {
      setRoutesSaveStatus("No hay cambios por guardar.");
      return true;
    }
    setRoutesSaveStatus("Guardando…");
    try {
      let failMessage = "";
      for (const key of keys) {
        const [origen, destino] = key.split("|||");
        const override = routeOverrides[key] ?? {};
        const response = await fetch("/api/routes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            origen,
            destino,
            km: override.km ?? 0,
            costo_por_km: override.costoPorKm ?? 0,
            enabled: override.enabled ?? true
          })
        });
        const data = await response.json();
        if (data.ok) {
          dirtyRoutes.current.delete(key);
        } else {
          failMessage = data.message ?? "No se pudo guardar.";
        }
      }
      if (failMessage) {
        setRoutesSaveStatus(failMessage);
        return false;
      }
      const hora = new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });
      setRoutesSaveStatus(`Guardado con éxito a las ${hora}.`);
      return true;
    } catch {
      setRoutesSaveStatus("Error de red al guardar.");
      return false;
    }
  }, [routeOverrides]);

  // Costo referencial (km × $/km) de una ruta habilitada; 0 si no existe/off.
  const routeCostRef = useCallback(
    (origen: string, destino: string) => {
      const override = routeOverrides[routeKey(origen, destino)];
      if (!override || override.enabled === false) return 0;
      return (override.km ?? 0) * (override.costoPorKm ?? 0);
    },
    [routeOverrides]
  );

  // Todos los productos del inventario (sin filtro), para asignarlos a estaciones.
  const allProducts = useMemo(
    () => Array.from(new Set(rows.map((row) => row.producto))).sort(),
    [rows]
  );

  // Estaciones de recepcion (cuello de botella del despacho). Configurables:
  // nombre, cupo de tanqueros/dia y productos asignados (arrastrables). Semilla
  // por keyword; se sobreescribe con lo guardado en Supabase / localStorage.
  const [stations, setStations] = useState<Station[]>(() =>
    defaultStationSeed(Array.from(new Set(sampleInventory.map((row) => row.producto))))
  );
  const dirtyStations = useRef(false);
  // True si las estaciones provienen de una fuente real (Supabase/localStorage), no de la
  // semilla demo. Evita que la semilla por keyword pise una configuracion guardada.
  const stationsFromRemote = useRef(false);
  const [stationsSaveStatus, setStationsSaveStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Supabase primero; si no hay, localStorage; si tampoco, se queda la semilla.
      try {
        const response = await fetch("/api/stations", { cache: "no-store" });
        const data = await response.json();
        if (!cancelled && data.ok && Array.isArray(data.stations) && data.stations.length > 0) {
          stationsFromRemote.current = true;
          setStations(data.stations.map(normalizeStation));
          return;
        }
      } catch {
        // sin Supabase
      }
      if (cancelled) return;
      try {
        const saved = localStorage.getItem("inventario_mp_app_stations");
        if (saved) {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed) && parsed.length > 0) {
            stationsFromRemote.current = true;
            setStations(parsed.map(normalizeStation));
          }
        }
      } catch {
        // localStorage no disponible
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const persistStationsLocal = useCallback((next: Station[]) => {
    try {
      localStorage.setItem("inventario_mp_app_stations", JSON.stringify(next));
    } catch {
      // ignore
    }
  }, []);

  const mutateStations = useCallback(
    (updater: (prev: Station[]) => Station[]) => {
      dirtyStations.current = true;
      setStationsSaveStatus("Cambios sin guardar");
      setStations((prev) => {
        const next = updater(prev);
        persistStationsLocal(next);
        return next;
      });
    },
    [persistStationsLocal]
  );

  const addStation = useCallback(() => {
    mutateStations((prev) => [
      ...prev,
      { id: `est-${Date.now()}`, nombre: `Estación ${prev.length + 1}`, tankers: 5, productos: [] }
    ]);
  }, [mutateStations]);

  const removeStation = useCallback(
    (id: string) => mutateStations((prev) => prev.filter((station) => station.id !== id)),
    [mutateStations]
  );

  const renameStation = useCallback(
    (id: string, nombre: string) =>
      mutateStations((prev) => prev.map((station) => (station.id === id ? { ...station, nombre } : station))),
    [mutateStations]
  );

  const updateStationTankers = useCallback(
    (id: string, tankers: number) =>
      mutateStations((prev) => prev.map((station) => (station.id === id ? { ...station, tankers } : station))),
    [mutateStations]
  );

  // Asigna un producto a una estacion (o lo deja sin asignar si stationId = null).
  // Lo quita de cualquier otra estacion (un producto va a una sola estacion).
  const assignProduct = useCallback(
    (producto: string, stationId: string | null) =>
      mutateStations((prev) =>
        prev.map((station) => ({
          ...station,
          productos:
            station.id === stationId
              ? Array.from(new Set([...station.productos, producto]))
              : station.productos.filter((item) => item !== producto)
        }))
      ),
    [mutateStations]
  );

  const saveStations = useCallback(async () => {
    setStationsSaveStatus("Guardando…");
    try {
      const response = await fetch("/api/stations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stations })
      });
      const data = await response.json();
      if (data.ok) {
        dirtyStations.current = false;
        const hora = new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });
        setStationsSaveStatus(`Guardado con éxito a las ${hora}.`);
        return true;
      }
      setStationsSaveStatus(data.message ?? "No se pudo guardar.");
      return false;
    } catch {
      setStationsSaveStatus("Error de red al guardar.");
      return false;
    }
  }, [stations]);

  // Origenes con ruta habilitada hacia la refineria (para el plan y la IA).
  const enabledSources = useMemo(
    () =>
      new Set(
        routes
          .filter((route) => route.enabled !== false && normalize(route.destino) === normalize(refineryName))
          .map((route) => route.origen)
      ),
    [routes]
  );

  const products = useMemo(() => ["TODOS", ...Array.from(new Set(rows.map((row) => row.producto)))], [rows]);
  const productRows = product === "TODOS" ? rows : rows.filter((row) => row.producto === product);
  const currentRows = getLatestInventoryRows(productRows);
  // Las visualizaciones temporales comparten ventana y granularidad: en diario,
  // los ultimos 30 dias; en mensual, el anio en curso colapsado por mes. Ambas
  // se anclan a la fecha mas reciente de los datos, no a "hoy".
  const windowedRows =
    granularity === "mensual" ? filterCurrentYear(productRows) : filterRecentDays(productRows, DAILY_WINDOW);
  // El mensual se calcula colapsando el diario, no re-agregando las filas: asi
  // el promedio del mes es el promedio de los totales por dia (un stock), y no
  // la suma de todas las filas del mes (que no significaria nada).
  const dailyHistory = buildInventoryHistory(windowedRows);
  const dailyHeatmap = buildLocationHeatmap(windowedRows);
  const inventoryHistory = granularity === "mensual" ? toMonthlyHistory(dailyHistory) : dailyHistory;
  const locationHeatmap = granularity === "mensual" ? toMonthlyHeatmap(dailyHeatmap) : dailyHeatmap;
  const refineryRows = currentRows.filter((row) => normalize(row.nombre) === normalize(refineryName));
  const kpis = getKpis(currentRows);
  const refineryKpis = getKpis(refineryRows);
  const enabledRoutes = routes.filter((route) => route.enabled !== false);
  const recommendations = buildRecommendations(currentRows, enabledRoutes, fleet);
  const distributionPlan = useMemo(
    () => buildDistributionPlan(currentRows, fleet, { enabledSources, routeCost: routeCostRef, stations }),
    [currentRows, fleet, enabledSources, routeCostRef, stations]
  );
  const dailyFleetCapacity = fleet.unidades * fleet.toneladasPorUnidad * fleet.viajesPorDia;
  // Ocupacion de flota: toneladas asignadas por el plan diario vs. capacidad diaria.
  const fleetOccupancy =
    distributionPlan.capacidadDiaria > 0
      ? distributionPlan.toneladasTotales / distributionPlan.capacidadDiaria
      : 0;
  const refineryOpenDemand = Math.max(
    0,
    sum(refineryRows.map((row) => row.pedido - row.retirado + row.pendienteRetiro - row.transito))
  );

  // Llamada cruda al analista IA con el contexto operativo. El `mode` decide el
  // prompt de sistema en /api/ai: "plan" devuelve las lineas parseables que
  // anotan el plan, "chat" responde en prosa la pregunta que se hizo. Sin ese
  // parametro el chat heredaba el formato de tarjetas y contestaba siempre con
  // el listado de despachos.
  async function callAi(question: string, mode: "plan" | "chat") {
    const response = await fetch("/api/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode, context: buildAiContext() })
    });
    const data = await response.json();
    return String(data.answer ?? "");
  }

  // "Revisar con IA" del plan de distribucion: UNA sola inferencia que devuelve
  // la lista de despachos que la IA propone. De ese texto salen las tarjetas que
  // anotan cada fila y el veredicto adversarial contra el MILP.
  const PREGUNTA_REVISION =
    "Revisa criticamente el plan de distribucion que viene en distributionPlan y propon tu propia lista de despachos para hoy. Coincide con el optimizador donde estes de acuerdo y apartate donde no, indicando en cada linea el motivo y el riesgo.";

  async function reviewPlan() {
    setLoadingPlanReview(true);
    setPlanReview("");
    try {
      setPlanReview(await callAi(PREGUNTA_REVISION, "plan"));
    } catch {
      setPlanReview("No se pudo completar la revisión del plan.");
    } finally {
      setLoadingPlanReview(false);
    }
  }

  // Chat del panel flotante. Cada consulta reemplaza la anterior: es un panel de
  // respuesta, no un hilo con historial.
  async function askTopic(pregunta: string) {
    setChatTopic(pregunta);
    setLoadingChat(true);
    setChatAnswer("");
    try {
      setChatAnswer(await callAi(pregunta, "chat"));
    } catch {
      setChatAnswer("No se pudo completar la consulta.");
    } finally {
      setLoadingChat(false);
    }
  }

  function buildAiContext() {
    return JSON.stringify(
      {
        kpis,
        refineryKpis,
        refineryOpenDemand,
        dailyFleetCapacity,
        fleet,
        // Para validar prioridad por acidez y espacio de almacenamiento:
        refineryFreeCapacity: getRefineryFreeCapacity(currentRows),
        puertoFreeCapacity: getPuertoFreeCapacity(currentRows),
        incomingByProduct: getIncomingByProduct(currentRows),
        extractoraStatus: getExtractoraStatus(currentRows),
        // Capacidad de recepcion: estaciones configurables (productos + cupo/dia).
        stations,
        distributionPlan,
        routes: enabledRoutes,
        topRecommendations: recommendations.slice(0, 8),
        inventoryHistory,
        rows: currentRows.slice(0, 30)
      },
      null,
      2
    );
  }


  return (
    <div className={`shell${navOpen ? "" : " nav-collapsed"}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">MP</div>
          <h1>Inventario Nacional</h1>
          <button
            type="button"
            className="nav-toggle"
            onClick={() => setNavOpen((value) => !value)}
            title={navOpen ? "Colapsar menú" : "Expandir menú"}
            aria-label={navOpen ? "Colapsar menú" : "Expandir menú"}
            aria-expanded={navOpen}
          >
            {navOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
        </div>
        <nav className="nav" aria-label="Principal">
          <NavButton active={view === "datos"} onClick={() => setView("datos")} icon={<SlidersHorizontal size={18} />} label="Datos maestros" />
          <NavButton active={view === "inventario"} onClick={() => setView("inventario")} icon={<Database size={18} />} label="Inventario" />
          <NavButton active={view === "rutas"} onClick={() => setView("rutas")} icon={<Route size={18} />} label="Rutas" />
          <NavButton active={view === "ia"} onClick={() => setView("ia")} icon={<Bot size={18} />} label="IA" />
        </nav>
        <div className="sidebar-note">
          Fuente actual: snapshots de inventario en Supabase, leídos server-side. La capa de datos queda lista
          para reemplazarse por SingleStore vía API.
        </div>
      </aside>

      <main className="main">
        <section className="topbar">
          <div>
            <h2>{viewTitle(view)}</h2>
            {viewSubtitle(view) && <p>{viewSubtitle(view)}</p>}
          </div>
          <div className="actions" />
        </section>

        {view === "rutas" && (
          <section className="grid kpis">
            <Kpi icon={<PackageCheck size={19} />} label="Inventario transportado" value={`${format(totalTransportado ?? distributionPlan.toneladasTotales)} t`} />
            <Kpi icon={<Gauge size={19} />} label="Ocupación flota" value={`${(fleetOccupancy * 100).toFixed(1)}%`} />
            <Kpi icon={<AlertTriangle size={19} />} label="Acidez ponderada" value={`${kpis.weightedAcidity.toFixed(2)}%`} />
            <Kpi icon={<Truck size={19} />} label="Capacidad flota diaria" value={`${format(dailyFleetCapacity)} t`} />
          </section>
        )}

        {view === "inventario" && (
          <section className="grid kpis">
            <Kpi icon={<PackageCheck size={19} />} label="Inventario neto" value={`${format(kpis.totalNetInventory)} t`} />
            <Kpi icon={<Gauge size={19} />} label="Ocupación nacional" value={`${(kpis.occupancy * 100).toFixed(1)}%`} />
            <Kpi icon={<AlertTriangle size={19} />} label="Acidez ponderada" value={`${kpis.weightedAcidity.toFixed(2)}%`} />
            <Kpi icon={<Truck size={19} />} label="Capacidad flota diaria" value={`${format(dailyFleetCapacity)} t`} />
          </section>
        )}

        {view === "inventario" && (
          <InventoryView
            rows={currentRows}
            products={products}
            product={product}
            setProduct={setProduct}
            granularity={granularity}
            setGranularity={setGranularity}
            history={inventoryHistory}
            heatmap={locationHeatmap}
            dataSource={dataSource}
          />
        )}

        {view === "rutas" && (
          <RoutesView
            plan={distributionPlan}
            fleet={fleet}
            routeCostRef={routeCostRef}
            dailyApproved={approvedSeries}
            granularity={planGranularity}
            setGranularity={setPlanGranularity}
            aiCards={priorityCards}
            stations={stations}
            enabledSources={enabledSources}
            refineryFree={getRefineryFreeCapacity(currentRows).byProduct}
            reviewPlan={reviewPlan}
            reviewLoading={loadingPlanReview}
            reviewDone={Boolean(planReview)}
            todayPlan={todayPlan}
            onApproved={refreshTransported}
          />
        )}

        {view === "datos" && (
          <DatosMaestrosView
            fleet={fleet}
            setFleet={setFleet}
            saveFleet={saveFleet}
            fleetSaveStatus={fleetSaveStatus}
            routes={routes}
            updateRoute={updateRoute}
            saveRoutes={saveRoutes}
            routesSaveStatus={routesSaveStatus}
            stations={stations}
            allProducts={allProducts}
            addStation={addStation}
            removeStation={removeStation}
            renameStation={renameStation}
            updateStationTankers={updateStationTankers}
            assignProduct={assignProduct}
            saveStations={saveStations}
            stationsSaveStatus={stationsSaveStatus}
          />
        )}

        {view === "ia" && (
          <section className="grid content-stack">
            <PipelineGraph dataSource={dataSource} metrics={processMetrics} />
          </section>
        )}

        <FloatingChat
          answer={chatAnswer}
          topic={chatTopic}
          loading={loadingChat}
          dataSource={dataSource}
          onAsk={askTopic}
        />
      </main>
    </div>
  );
}

function InventoryView({
  rows,
  products,
  product,
  setProduct,
  granularity,
  setGranularity,
  history,
  heatmap,
  dataSource
}: {
  rows: InventoryRow[];
  products: string[];
  product: string;
  setProduct: (value: string) => void;
  granularity: Granularity;
  setGranularity: (value: Granularity) => void;
  history: ReturnType<typeof buildInventoryHistory>;
  heatmap: ReturnType<typeof buildLocationHeatmap>;
  dataSource: DataSource;
}) {
  const [tankCollapsed, setTankCollapsed] = useState(false);

  return (
    <section className="grid content-stack">
      <div className="inventory-filter">
        <span>Producto</span>
        <select value={product} onChange={(event) => setProduct(event.target.value)} aria-label="Producto">
          {products.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <span>Vista</span>
        <div className="range-toggle" role="group" aria-label="Granularidad">
          {([
            { value: "diario", label: `${DAILY_WINDOW} días` },
            { value: "mensual", label: "Mensual" }
          ] as const).map((option) => (
            <button
              key={option.value}
              type="button"
              className={granularity === option.value ? "active" : ""}
              aria-pressed={granularity === option.value}
              onClick={() => setGranularity(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <InventoryHistoryChart history={history} dataSource={dataSource} granularity={granularity} />
      <LocationHeatmap heatmap={heatmap} granularity={granularity} />
      <div className="card">
        <div className="section-title">
          <button
            type="button"
            className="collapse-title"
            onClick={() => setTankCollapsed((value) => !value)}
            aria-expanded={!tankCollapsed}
          >
            {tankCollapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
            <div>
              <h3>Inventario por tanque</h3>
            </div>
          </button>
        </div>
        {!tankCollapsed && <InventoryTable rows={rows} />}
      </div>
    </section>
  );
}

function InventoryHistoryChart({
  history,
  dataSource,
  granularity
}: {
  history: ReturnType<typeof buildInventoryHistory>;
  dataSource: DataSource;
  granularity: Granularity;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const isMonthly = granularity === "mensual";

  if (history.length === 0) {
    return (
      <div className="card history-card">
        <div className="section-title">
          <div>
            <h3>Histórico de inventario</h3>
            <p className="section-note">Stock disponible en tanques vs. stock en tránsito por fecha.</p>
          </div>
        </div>
        <div className="empty-state">Sin snapshots de inventario para el rango seleccionado.</div>
      </div>
    );
  }

  const width = 720;
  const height = 260;
  const padding = { top: 18, right: 20, bottom: 34, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...history.flatMap((point) => [point.stock, point.transito]), 1);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(maxValue * ratio));
  const latest = history[history.length - 1];
  const first = history[0];
  const change = latest && first ? latest.stock - first.stock : 0;
  // hoveredIndex es estado del componente y sobrevive a los cambios de serie:
  // al pasar de diario (30 puntos) a mensual (8) un indice viejo queda fuera de
  // rango. Se valida contra la longitud actual en vez de indexar a ciegas.
  const hoveredPoint = hoveredIndex !== null && hoveredIndex < history.length ? history[hoveredIndex] : null;
  const labelStep = Math.max(1, Math.ceil(history.length / 8));

  // Barras agrupadas: cada fecha ocupa una banda y dentro van las dos series
  // lado a lado. A diferencia de la linea, la posicion X ya no es un punto sino
  // el centro de esa banda.
  const band = plotWidth / history.length;
  const barGap = 2;
  // Ancho acotado: con 8 barras mensuales no deben salir columnas enormes, y
  // con 30 diarias tienen que seguir siendo visibles.
  const barWidth = Math.max(1.5, Math.min(16, (band - barGap) / 2 - barGap / 2));
  const baseline = padding.top + plotHeight;

  const xFor = (index: number) => padding.left + band * (index + 0.5);
  const yFor = (value: number) => padding.top + plotHeight - (value / maxValue) * plotHeight;
  const barHeight = (value: number) => Math.max(0, baseline - yFor(value));
  const tooltipWidth = 188;
  const tooltipHeight = 90;
  const tooltipX =
    hoveredPoint === null ? 0 : Math.min(width - tooltipWidth - 10, Math.max(10, xFor(hoveredIndex!) - tooltipWidth / 2));
  // Se ancla sobre la barra mas alta del grupo para no taparla.
  const tooltipY =
    hoveredPoint === null
      ? 0
      : Math.max(
          10,
          Math.min(
            height - tooltipHeight - 10,
            Math.min(yFor(hoveredPoint.stock), yFor(hoveredPoint.transito)) - tooltipHeight - 12
          )
        );

  return (
    <div className="card history-card">
      <div className="section-title">
        <div>
          <h3>Histórico de inventario</h3>
          <p className="section-note">
            {isMonthly
              ? "Promedio mensual del inventario filtrado, año en curso."
              : `Totales por fecha del inventario filtrado, últimos ${DAILY_WINDOW} días.`}
          </p>
        </div>
        <div className="history-actions">
          <span className={`source-badge ${dataSource === "supabase" ? "live" : ""}`}>
            {dataSource === "supabase" ? "Supabase" : "Datos demo"}
          </span>
          <div className={`trend ${change < 0 ? "down" : "up"}`}>
            <LineChart size={16} />
            {change === 0 ? "Sin variación" : `${change > 0 ? "+" : ""}${format(change)} t`}
          </div>
        </div>
      </div>
      <div className="chart-wrap" aria-label="Grafico historico de inventario" onMouseLeave={() => setHoveredIndex(null)}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img">
          {yTicks.map((tick) => (
            <g key={tick}>
              <line x1={padding.left} x2={width - padding.right} y1={yFor(tick)} y2={yFor(tick)} className="gridline" />
              <text x={padding.left - 10} y={yFor(tick) + 4} textAnchor="end">
                {format(tick)}
              </text>
            </g>
          ))}
          {history.map((point, index) => {
            const isHovered = hoveredIndex === index;
            const showLabel = index % labelStep === 0 || index === history.length - 1;
            const centro = xFor(index);
            return (
              <g key={point.date}>
                {/* Banda del grupo: marca la fecha señalada sin tapar las barras. */}
                {isHovered && (
                  <rect
                    x={centro - band / 2}
                    y={padding.top}
                    width={band}
                    height={plotHeight}
                    className="bar-band"
                  />
                )}
                <rect
                  x={centro - barGap / 2 - barWidth}
                  y={yFor(point.stock)}
                  width={barWidth}
                  height={barHeight(point.stock)}
                  className={`bar bar-inventory${isHovered ? " active" : ""}`}
                />
                <rect
                  x={centro + barGap / 2}
                  y={yFor(point.transito)}
                  width={barWidth}
                  height={barHeight(point.transito)}
                  className={`bar bar-transito${isHovered ? " active" : ""}`}
                />
                {showLabel && (
                  <text x={centro} y={height - 10} textAnchor="middle">
                    {bucketShortLabel(point.date, granularity)}
                  </text>
                )}
              </g>
            );
          })}
          <rect
            x={padding.left}
            y={padding.top}
            width={plotWidth}
            height={plotHeight}
            className="chart-hit-area"
            onMouseMove={(event) => {
              const svg = event.currentTarget.ownerSVGElement;
              if (!svg) return;
              const bounds = svg.getBoundingClientRect();
              const xPx = ((event.clientX - bounds.left) / bounds.width) * width;
              // Con barras el puntero cae DENTRO de una banda, no cerca de un
              // punto: se divide entre bandas en vez de redondear al vertice.
              const index = Math.floor((xPx - padding.left) / band);
              setHoveredIndex(Math.max(0, Math.min(history.length - 1, index)));
            }}
          />
          {hoveredIndex !== null && hoveredPoint && (
            <g className="chart-tooltip">
              {/* Sin linea vertical: la banda resaltada ya señala el grupo. */}
              <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="8" />
              <text x={tooltipX + 12} y={tooltipY + 22} className="tooltip-title">
                {bucketLongLabel(hoveredPoint.date, granularity)}
              </text>
              <text x={tooltipX + 12} y={tooltipY + 44}>Inventario: {format(hoveredPoint.stock)} t</text>
              <text x={tooltipX + 12} y={tooltipY + 62}>En tránsito: {format(hoveredPoint.transito)} t</text>
              <text x={tooltipX + 12} y={tooltipY + 80}>
                Ocupación: {hoveredPoint.capacidad > 0 ? `${((hoveredPoint.stock / hoveredPoint.capacidad) * 100).toFixed(1)}%` : "s/d"}
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="legend">
        <span><i className="legend-dot inventory" />Inventario (disponible)</span>
        <span><i className="legend-dot available" />Stock en tránsito</span>
        <span>
          {isMonthly ? "Promedio último mes: " : "Último inventario: "}
          <strong>{latest ? `${format(latest.stock)} t` : "0 t"}</strong>
        </span>
      </div>
    </div>
  );
}

function LocationHeatmap({
  heatmap,
  granularity
}: {
  heatmap: ReturnType<typeof buildLocationHeatmap>;
  granularity: Granularity;
}) {
  const { dates, locations } = heatmap;
  const isMonthly = granularity === "mensual";
  // A alta densidad el % no cabe en la celda: solo color, el dato exacto queda en
  // el tooltip (title). Las etiquetas se muestran cada colLabelStep.
  const DENSE_COLS = 31;
  const showCellText = dates.length <= DENSE_COLS;
  const colLabelStep = Math.max(1, Math.ceil(dates.length / 12));

  return (
    <div className="card heatmap-card">
      <div className="section-title">
        <div>
          <h3>Ocupación por ubicación</h3>
          <p className="section-note">
            Solo ubicaciones con tanque · disponible ÷ capacidad
            {isMonthly ? " · promedio por mes" : ", por fecha"}.
          </p>
        </div>
        <div className="heat-scale" aria-hidden="true">
          <span>0%</span>
          <i className="heat-scale-bar" />
          <span>100%</span>
        </div>
      </div>
      {dates.length === 0 || locations.length === 0 ? (
        <div className="empty-state">Sin snapshots de inventario para el rango seleccionado.</div>
      ) : (
        <div className="heatmap-wrap">
          <div
            className="heatmap-grid"
            style={{ gridTemplateColumns: `clamp(72px, 14%, 120px) repeat(${dates.length}, minmax(0, 1fr))` }}
          >
            <div className="heat-corner" />
            {dates.map((date, index) => (
              <div key={date} className="heat-col-label" title={bucketLongLabel(date, granularity)}>
                {index % colLabelStep === 0 || index === dates.length - 1
                  ? bucketShortLabel(date, granularity)
                  : ""}
              </div>
            ))}
            {locations.map((location) => (
              <Fragment key={location.nombre}>
                <div className="heat-row-label" title={location.nombre}>
                  {location.nombre}
                </div>
                {location.cells.map((cell) => (
                  <div
                    key={`${location.nombre}-${cell.date}`}
                    className={`heat-cell ${cell.occupancy === null ? "empty" : ""}`}
                    style={
                      cell.occupancy === null
                        ? undefined
                        : { background: heatColor(cell.occupancy), color: heatTextColor(cell.occupancy) }
                    }
                    title={
                      cell.occupancy === null
                        ? `${location.nombre} · ${bucketLongLabel(cell.date, granularity)}: sin dato`
                        : `${location.nombre} · ${bucketLongLabel(cell.date, granularity)}${isMonthly ? " (promedio)" : ""}\nOcupación ${(cell.occupancy * 100).toFixed(1)}%\nDisponible ${format(cell.disponible)} t / Capacidad ${format(cell.capacidad)} t`
                    }
                  >
                    {!showCellText ? "" : cell.occupancy === null ? "–" : `${Math.round(cell.occupancy * 100)}%`}
                  </div>
                ))}
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RoutesView({
  plan,
  fleet,
  routeCostRef,
  dailyApproved,
  granularity,
  setGranularity,
  aiCards,
  stations,
  enabledSources,
  refineryFree,
  reviewPlan,
  reviewLoading,
  reviewDone,
  todayPlan,
  onApproved
}: {
  plan: DistributionPlan;
  fleet: FleetInput;
  routeCostRef: (origen: string, destino: string) => number;
  dailyApproved: DailyApproved[];
  granularity: Granularity;
  setGranularity: (value: Granularity) => void;
  aiCards: AiCard[];
  stations: Station[];
  enabledSources: Set<string>;
  refineryFree: Record<string, number>;
  reviewPlan: () => void;
  reviewLoading: boolean;
  reviewDone: boolean;
  todayPlan: StoredPlan | null;
  onApproved: () => void;
}) {
  return (
    <section className="grid content-stack">
      <FleetCostChart daily={dailyApproved} granularity={granularity} setGranularity={setGranularity} />

      <DistributionPlanCard
        plan={plan}
        fleet={fleet}
        routeCostRef={routeCostRef}
        aiCards={aiCards}
        stations={stations}
        enabledSources={enabledSources}
        refineryFree={refineryFree}
        reviewPlan={reviewPlan}
        reviewLoading={reviewLoading}
        reviewDone={reviewDone}
        todayPlan={todayPlan}
        onApproved={onApproved}
      />
    </section>
  );
}

function DatosMaestrosView({
  fleet,
  setFleet,
  saveFleet,
  fleetSaveStatus,
  routes,
  updateRoute,
  saveRoutes,
  routesSaveStatus,
  stations,
  allProducts,
  addStation,
  removeStation,
  renameStation,
  updateStationTankers,
  assignProduct,
  saveStations,
  stationsSaveStatus
}: {
  fleet: FleetInput;
  setFleet: (value: FleetInput) => void;
  saveFleet: () => Promise<boolean>;
  fleetSaveStatus: string;
  routes: RouteCost[];
  updateRoute: (origen: string, destino: string, patch: Partial<RouteCost>) => void;
  saveRoutes: () => Promise<boolean>;
  routesSaveStatus: string;
  stations: Station[];
  allProducts: string[];
  addStation: () => void;
  removeStation: (id: string) => void;
  renameStation: (id: string, nombre: string) => void;
  updateStationTankers: (id: string, value: number) => void;
  assignProduct: (producto: string, stationId: string | null) => void;
  saveStations: () => Promise<boolean>;
  stationsSaveStatus: string;
}) {
  return (
    <section className="grid content-stack">
      <FleetCard fleet={fleet} setFleet={setFleet} saveFleet={saveFleet} fleetSaveStatus={fleetSaveStatus} />
      <RoutesMatrixCard
        routes={routes}
        updateRoute={updateRoute}
        saveRoutes={saveRoutes}
        routesSaveStatus={routesSaveStatus}
      />
      <StationsCard
        stations={stations}
        allProducts={allProducts}
        addStation={addStation}
        removeStation={removeStation}
        renameStation={renameStation}
        updateStationTankers={updateStationTankers}
        assignProduct={assignProduct}
        saveStations={saveStations}
        stationsSaveStatus={stationsSaveStatus}
      />
    </section>
  );
}

function FleetCard({
  fleet,
  setFleet,
  saveFleet,
  fleetSaveStatus
}: {
  fleet: FleetInput;
  setFleet: (value: FleetInput) => void;
  saveFleet: () => Promise<boolean>;
  fleetSaveStatus: string;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const dailyCapacity = fleet.unidades * fleet.toneladasPorUnidad * fleet.viajesPorDia;

  async function handleSave() {
    const ok = await saveFleet();
    if (ok) setCollapsed(true);
  }

  return (
    <div className="card">
      <div className="section-title">
        <button
          type="button"
          className="collapse-title"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
          <div>
            <h3>Flota disponible</h3>
            {!collapsed && (
              <p className="section-note">
                Número de transportes y toneladas por transporte. Capacidad diaria = transportes × toneladas ×
                viajes/día.
              </p>
            )}
          </div>
        </button>
        <div className="routes-save">
          {fleetSaveStatus && <span className="section-note">{fleetSaveStatus}</span>}
          {!collapsed && (
            <button className="btn primary" onClick={handleSave}>
              <Save size={16} /> Guardar
            </button>
          )}
        </div>
      </div>
      {!collapsed && (
        <div className="reception-grid">
          <label className="reception-item">
            <span className="reception-name">Número de transportes</span>
            <span className="reception-products">Tanqueros disponibles en la flota</span>
            <div className="reception-input">
              <input
                className="cell-input cell-input--num"
                type="number"
                min={0}
                value={fleet.unidades}
                onChange={(event) => setFleet({ ...fleet, unidades: Number(event.target.value) || 0 })}
              />
              <span className="section-note">tanqueros</span>
            </div>
          </label>
          <label className="reception-item">
            <span className="reception-name">Toneladas por transporte</span>
            <span className="reception-products">Carga de cada tanquero</span>
            <div className="reception-input">
              <input
                className="cell-input cell-input--num"
                type="number"
                min={0}
                value={fleet.toneladasPorUnidad}
                onChange={(event) => setFleet({ ...fleet, toneladasPorUnidad: Number(event.target.value) || 0 })}
              />
              <span className="section-note">t/tanquero</span>
            </div>
          </label>
          <div className="reception-item">
            <span className="reception-name">Capacidad diaria</span>
            <span className="reception-products">Transportes × toneladas × viajes</span>
            <div className="reception-input">
              <strong>{format(dailyCapacity)} t</strong>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RoutesMatrixCard({
  routes,
  updateRoute,
  saveRoutes,
  routesSaveStatus
}: {
  routes: RouteCost[];
  updateRoute: (origen: string, destino: string, patch: Partial<RouteCost>) => void;
  saveRoutes: () => Promise<boolean>;
  routesSaveStatus: string;
}) {
  const [collapsed, setCollapsed] = useState(true);

  async function handleSave() {
    const ok = await saveRoutes();
    if (ok) setCollapsed(true);
  }

  return (
    <div className="card">
      <div className="section-title">
        <button
          type="button"
          className="collapse-title"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
          <div>
            <h3>Matriz de rutas</h3>
            {!collapsed && (
              <p className="section-note">
                Edita km y $/km (costo ref. = km × $/km), input del plan. El check habilita o
                deshabilita cada nodo. Guarda para persistir en Supabase.
              </p>
            )}
          </div>
        </button>
        <div className="routes-save">
          {routesSaveStatus && <span className="section-note">{routesSaveStatus}</span>}
          {!collapsed && (
            <button className="btn primary" onClick={handleSave}>
              <Save size={16} /> Guardar
            </button>
          )}
        </div>
      </div>
      {!collapsed &&
        (routes.length === 0 ? (
          <div className="empty-state">Carga datos con ubicaciones de tanque para ver las rutas.</div>
        ) : (
          <div className="table-wrap">
            <table className="routes-table">
              <thead>
                <tr>
                  <th>Origen</th>
                  <th>Destino</th>
                  <th>Km</th>
                  <th>$/km</th>
                  <th>Costo ref.</th>
                  <th>Nodos</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((route) => {
                  const enabled = route.enabled !== false;
                  return (
                    <tr key={routeKey(route.origen, route.destino)} className={enabled ? "" : "route-off"}>
                      <td>{route.origen}</td>
                      <td>{route.destino}</td>
                      <td>
                        <input
                          className="cell-input cell-input--num"
                          type="number"
                          min={0}
                          value={route.km}
                          onChange={(event) =>
                            updateRoute(route.origen, route.destino, { km: Number(event.target.value) || 0 })
                          }
                        />
                      </td>
                      <td>
                        <input
                          className="cell-input cell-input--num"
                          type="number"
                          min={0}
                          step="0.01"
                          value={route.costoPorKm}
                          onChange={(event) =>
                            updateRoute(route.origen, route.destino, { costoPorKm: Number(event.target.value) || 0 })
                          }
                        />
                      </td>
                      <td>${format(route.km * route.costoPorKm)}</td>
                      <td>
                        <button
                          type="button"
                          className={`node-toggle ${enabled ? "on" : "off"}`}
                          onClick={() => updateRoute(route.origen, route.destino, { enabled: !enabled })}
                          title={enabled ? "Nodo habilitado" : "Nodo deshabilitado"}
                          aria-pressed={enabled}
                        >
                          {enabled ? "✓" : "✗"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}

function StationsCard({
  stations,
  allProducts,
  addStation,
  removeStation,
  renameStation,
  updateStationTankers,
  assignProduct,
  saveStations,
  stationsSaveStatus
}: {
  stations: Station[];
  allProducts: string[];
  addStation: () => void;
  removeStation: (id: string) => void;
  renameStation: (id: string, nombre: string) => void;
  updateStationTankers: (id: string, value: number) => void;
  assignProduct: (producto: string, stationId: string | null) => void;
  saveStations: () => Promise<boolean>;
  stationsSaveStatus: string;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [dragProduct, setDragProduct] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const assigned = new Set(stations.flatMap((station) => station.productos));
  const unassigned = allProducts.filter((producto) => !assigned.has(producto));

  function handleDrop(stationId: string | null) {
    if (dragProduct) assignProduct(dragProduct, stationId);
    setDragProduct(null);
    setOverId(null);
  }

  async function handleSave() {
    const ok = await saveStations();
    if (ok) setCollapsed(true);
  }

  return (
    <div className="card">
      <div className="section-title">
        <button
          type="button"
          className="collapse-title"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
          <div>
            <h3>Estaciones de recepción</h3>
            {!collapsed && (
              <p className="section-note">
                Cupo de tanqueros/día por estación (cuello de botella del despacho). Arrastra los productos a cada
                estación; lo que quede en “Sin asignar” se excluye del plan. Aprovéchala entre semana para evitar horas
                extra el fin de semana.
              </p>
            )}
          </div>
        </button>
        <div className="routes-save">
          {stationsSaveStatus && <span className="section-note">{stationsSaveStatus}</span>}
          {!collapsed && (
            <>
              <button className="btn" onClick={addStation}>
                <Plus size={16} /> Agregar estación
              </button>
              <button className="btn primary" onClick={handleSave}>
                <Save size={16} /> Guardar
              </button>
            </>
          )}
        </div>
      </div>
      {!collapsed && (
        <>
          <div className="stations-grid">
            {stations.map((station) => (
              <div
                key={station.id}
                className={`station-card${overId === station.id ? " over" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setOverId(station.id);
                }}
                onDragLeave={() => setOverId((current) => (current === station.id ? null : current))}
                onDrop={() => handleDrop(station.id)}
              >
                <div className="station-head">
                  <input
                    className="cell-input station-name"
                    value={station.nombre}
                    onChange={(event) => renameStation(station.id, event.target.value)}
                  />
                  <button
                    type="button"
                    className="station-remove"
                    onClick={() => removeStation(station.id)}
                    title="Eliminar estación"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                <label className="station-tankers">
                  <input
                    className="cell-input cell-input--num"
                    type="number"
                    min={0}
                    value={station.tankers}
                    onChange={(event) => updateStationTankers(station.id, Number(event.target.value) || 0)}
                  />
                  <span className="section-note">tanqueros/día</span>
                </label>
                <div className="station-dropzone">
                  {station.productos.length === 0 ? (
                    <span className="dropzone-hint">Arrastra productos aquí</span>
                  ) : (
                    station.productos.map((producto) => (
                      <span
                        key={producto}
                        className="product-chip"
                        draggable
                        onDragStart={() => setDragProduct(producto)}
                        onDragEnd={() => setDragProduct(null)}
                      >
                        {producto}
                        <button
                          type="button"
                          className="chip-x"
                          onClick={() => assignProduct(producto, null)}
                          title="Quitar de la estación"
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
          <div
            className={`station-pool${overId === "pool" ? " over" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setOverId("pool");
            }}
            onDragLeave={() => setOverId((current) => (current === "pool" ? null : current))}
            onDrop={() => handleDrop(null)}
          >
            <div className="pool-head">
              <strong>Sin asignar</strong>
              <span className="section-note">No entran al plan hasta asignarlos a una estación.</span>
            </div>
            <div className="pool-chips">
              {unassigned.length === 0 ? (
                <span className="dropzone-hint">Todos los productos están asignados.</span>
              ) : (
                unassigned.map((producto) => (
                  <span
                    key={producto}
                    className="product-chip"
                    draggable
                    onDragStart={() => setDragProduct(producto)}
                    onDragEnd={() => setDragProduct(null)}
                  >
                    {producto}
                  </span>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function FleetCostChart({
  daily,
  granularity,
  setGranularity
}: {
  daily: DailyApproved[];
  granularity: Granularity;
  setGranularity: (value: Granularity) => void;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const isMonthly = granularity === "mensual";
  const title = isMonthly ? "Camiones y costo por mes" : "Camiones y costo por día";

  const toggle = (
    <div className="range-toggle" role="group" aria-label="Granularidad">
      {([
        { value: "diario", label: `${DAILY_WINDOW} días` },
        { value: "mensual", label: "Mensual" }
      ] as const).map((option) => (
        <button
          key={option.value}
          type="button"
          className={granularity === option.value ? "active" : ""}
          aria-pressed={granularity === option.value}
          onClick={() => setGranularity(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );

  if (daily.length === 0) {
    return (
      <div className="card history-card">
        <div className="section-title">
          <div>
            <h3>{title}</h3>
            <p className="section-note">Histórico de planes aprobados (Supabase).</p>
          </div>
          {toggle}
        </div>
        <div className="empty-state">Aprueba planes para ver la asignación de camiones y el costo.</div>
      </div>
    );
  }

  const width = 720;
  const height = 260;
  const padding = { top: 18, right: 20, bottom: 34, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maxCamiones = Math.max(...daily.map((point) => point.camiones), 1);
  const maxCosto = Math.max(...daily.map((point) => point.costo), 1);
  const latest = daily[daily.length - 1];

  const xFor = (index: number) =>
    padding.left + (daily.length === 1 ? plotWidth / 2 : (index / (daily.length - 1)) * plotWidth);
  const yCamiones = (value: number) => padding.top + plotHeight - (value / maxCamiones) * plotHeight;
  const yCosto = (value: number) => padding.top + plotHeight - (value / maxCosto) * plotHeight;
  const lineFor = (accessor: (point: DailyApproved) => number, scale: (value: number) => number) =>
    daily.map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(index)} ${scale(accessor(point))}`).join(" ");

  const tooltipWidth = 190;
  const tooltipHeight = 72;
  // Mismo caso que en InventoryHistoryChart: al cambiar de diario (30 puntos) a
  // mensual (8) el hoveredIndex guardado puede apuntar fuera del arreglo.
  const hoveredPoint = hoveredIndex !== null && hoveredIndex < daily.length ? daily[hoveredIndex] : null;
  const tooltipX =
    hoveredPoint === null ? 0 : Math.min(width - tooltipWidth - 10, Math.max(10, xFor(hoveredIndex!) - tooltipWidth / 2));
  const tooltipY =
    hoveredPoint === null ? 0 : Math.max(10, yCamiones(hoveredPoint.camiones) - tooltipHeight - 12);

  return (
    <div className="card history-card">
      <div className="section-title">
        <div>
          <h3>{title}</h3>
          <p className="section-note">
            {isMonthly
              ? "Planes aprobados: total por mes del año en curso (Supabase)."
              : `Planes aprobados: últimos ${DAILY_WINDOW} días con despachos (Supabase).`}
          </p>
        </div>
        <div className="legend">
          <span><i className="legend-dot inventory" />Camiones</span>
          <span><i className="legend-dot available" />Costo ($)</span>
          <span>
            {isMonthly ? "Último mes: " : "Último: "}
            <strong>{format(latest.camiones)} cam · ${format(latest.costo)}</strong>
          </span>
          {toggle}
        </div>
      </div>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" className="chart-svg">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <line
              key={ratio}
              x1={padding.left}
              x2={width - padding.right}
              y1={padding.top + plotHeight * ratio}
              y2={padding.top + plotHeight * ratio}
              className="grid-line"
            />
          ))}
          <path d={lineFor((point) => point.costo, yCosto)} className="chart-line available-line" />
          <path d={lineFor((point) => point.camiones, yCamiones)} className="chart-line inventory-line" />
          {daily.map((point, index) => (
            <g
              key={point.fecha}
              className="chart-hit-group"
              onMouseEnter={() => setHoveredIndex(index)}
              onFocus={() => setHoveredIndex(index)}
              tabIndex={0}
            >
              <rect
                x={xFor(index) - Math.max(18, plotWidth / Math.max(daily.length, 1) / 2)}
                y={padding.top}
                width={Math.max(36, plotWidth / Math.max(daily.length, 1))}
                height={plotHeight}
                className="chart-hit-area"
              />
              <circle cx={xFor(index)} cy={yCamiones(point.camiones)} r={hoveredIndex === index ? "6" : "4"} className="inventory-dot" />
              <circle cx={xFor(index)} cy={yCosto(point.costo)} r={hoveredIndex === index ? "6" : "4"} className="available-dot" />
              {(index === 0 || index === daily.length - 1 || daily.length <= 12) && (
                <text x={xFor(index)} y={height - 10} textAnchor="middle">
                  {bucketShortLabel(point.fecha, granularity)}
                </text>
              )}
            </g>
          ))}
          {hoveredIndex !== null && hoveredPoint && (
            <g className="chart-tooltip">
              <line x1={xFor(hoveredIndex)} x2={xFor(hoveredIndex)} y1={padding.top} y2={padding.top + plotHeight} className="hover-line" />
              <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="8" />
              <text x={tooltipX + 12} y={tooltipY + 22} className="tooltip-title">
                {bucketLongLabel(hoveredPoint.fecha, granularity)}
              </text>
              <text x={tooltipX + 12} y={tooltipY + 44}>Camiones: {format(hoveredPoint.camiones)}</text>
              <text x={tooltipX + 12} y={tooltipY + 62}>Costo: ${format(hoveredPoint.costo)}</text>
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}

// Lo editable de cada despacho. Se edita el numero de TANQUEROS, no las
// toneladas: la capacidad por tanquero es fija (fleet.toneladasPorUnidad), asi
// que las toneladas son un valor derivado y no un dato independiente. Editar
// toneladas permitia pedir cargas que ningun numero entero de tanqueros puede
// transportar.
type DispatchFields = {
  camiones: string;
  partida: string;
  destino: string;
};

function stopKey(stop: DistributionPlan["stops"][number], index: number) {
  return `${stop.origen}-${stop.tanque}-${stop.producto}-${index}`;
}

// Fila guardada en Supabase -> fila de plan. `estacion` y `urgency` no se
// persisten: son internos del optimizador y no se muestran ni se reenvian, asi
// que se rellenan con valores neutros.
function storedToStop(row: StoredStop): DistributionStop {
  return {
    origen: row.partida,
    producto: row.producto,
    tanque: row.tanque,
    estacion: "",
    occupancy: row.occupancy,
    acidez: row.acidez,
    urgency: 0,
    toneladas: row.toneladas,
    camiones: row.camiones,
    viajesPorCamion: row.viajesPorCamion || 1,
    costo: row.costo
  };
}

// Producto mencionado en la tarjeta. El detalle sigue el formato
// "DESTINO, PRODUCTO, N t": se descartan el segmento del tonelaje y el del
// destino, y lo que queda es el producto.
function productoFromCard(card: AiCard) {
  const partes = card.detail
    .split(",")
    .map((parte) => parte.trim())
    .filter((parte) => parte && !/^[\d.,]+\s*t$/i.test(parte) && normalize(parte) !== normalize(refineryName));
  return partes[0] ?? "";
}

// Convierte una sugerencia de la IA en una fila de despacho. Deriva camiones y
// viajes igual que el optimizador (toneladas / capacidad por unidad), pero NO
// valida ninguna restriccion: cupo de estacion, capacidad libre de la refineria
// ni ruta habilitada. Por eso la fila queda marcada como añadida a mano.
function stopFromCard(card: AiCard, fleet: FleetInput): DistributionStop | null {
  const toneladas = aiToneladas(card);
  if (!toneladas) return null;

  const truckCap = fleet.toneladasPorUnidad > 0 ? fleet.toneladasPorUnidad : 1;
  const tripsPerTruck = fleet.viajesPorDia > 0 ? fleet.viajesPorDia : 1;
  const trips = Math.max(1, Math.ceil(toneladas / truckCap));
  const camiones = Math.ceil(trips / tripsPerTruck);

  return {
    origen: card.title,
    producto: productoFromCard(card),
    tanque: "",
    estacion: "",
    occupancy: 0,
    acidez: 0,
    urgency: 0,
    toneladas,
    camiones,
    viajesPorCamion: Math.ceil(trips / camiones),
    costo: 0 // lo recalcula costoFor() con la matriz de rutas
  };
}

function DistributionPlanCard({
  plan,
  fleet,
  routeCostRef,
  aiCards,
  stations,
  enabledSources,
  refineryFree,
  reviewPlan,
  reviewLoading,
  reviewDone,
  todayPlan,
  onApproved
}: {
  plan: DistributionPlan;
  fleet: FleetInput;
  routeCostRef: (origen: string, destino: string) => number;
  aiCards: AiCard[];
  stations: Station[];
  enabledSources: Set<string>;
  refineryFree: Record<string, number>;
  reviewPlan: () => void;
  reviewLoading: boolean;
  reviewDone: boolean;
  todayPlan: StoredPlan | null;
  onApproved: () => void;
}) {
  const [edits, setEdits] = useState<Record<string, DispatchFields>>({});
  // Sugerencias de la IA que el usuario añadio al plan a mano. Viven aparte de
  // plan.stops porque no las produjo el optimizador.
  const [extras, setExtras] = useState<DistributionStop[]>([]);
  // Confirmacion explicita para aprobar un plan que incumple restricciones.
  const [overrideAvisos, setOverrideAvisos] = useState(false);
  const [approving, setApproving] = useState(false);
  // plan_id del plan guardado en Supabase. Es el que manda: mientras no sea
  // null hay un plan aprobado alla, y sirve para reemplazarlo o borrarlo.
  const [approvedPlanId, setApprovedPlanId] = useState<string | null>(null);
  // Un plan aprobado se ve en solo lectura; "Editar" lo reabre.
  const [editing, setEditing] = useState(false);
  // Foto de los valores tal como se guardaron, para que "Cancelar" descarte los
  // cambios en curso y no deje la tabla mostrando algo distinto de la base.
  const [savedState, setSavedState] = useState<{ edits: Record<string, DispatchFields>; extras: DistributionStop[] } | null>(null);
  // Filas del plan aprobado. Mientras exista, sustituyen a las del optimizador
  // como base de la tabla.
  const [approvedStops, setApprovedStops] = useState<DistributionStop[] | null>(null);
  const [status, setStatus] = useState("");

  const approved = approvedPlanId !== null;
  // Bloqueo de la tabla: aprobado y sin edicion abierta.
  const locked = approved && !editing;

  // Rehidratacion: si Supabase ya tiene un plan aprobado hoy, la tarjeta arranca
  // bloqueada con esas filas. Se corre una vez por plan_id (el ref evita pisar
  // lo que el usuario este editando cuando /api/plan se vuelve a consultar).
  const hydratedPlanId = useRef<string | null>(null);
  useEffect(() => {
    if (!todayPlan || hydratedPlanId.current === todayPlan.planId) return;
    hydratedPlanId.current = todayPlan.planId;

    const stops = todayPlan.stops.map(storedToStop);
    const nextEdits: Record<string, DispatchFields> = {};
    todayPlan.stops.forEach((row, index) => {
      nextEdits[stopKey(stops[index], index)] = {
        camiones: String(row.camiones),
        partida: row.partida,
        destino: row.destino || refineryName
      };
    });

    setApprovedStops(stops);
    setEdits(nextEdits);
    setExtras([]);
    setApprovedPlanId(todayPlan.planId);
    setEditing(false);
    setSavedState({ edits: nextEdits, extras: [] });
  }, [todayPlan]);

  function fieldsFor(stop: DistributionPlan["stops"][number], index: number): DispatchFields {
    const key = stopKey(stop, index);
    return (
      edits[key] ?? {
        camiones: String(stop.camiones),
        partida: stop.origen,
        destino: refineryName
      }
    );
  }

  function update(key: string, base: DispatchFields, field: keyof DispatchFields, value: string) {
    setEdits((prev) => ({ ...prev, [key]: { ...base, [field]: value } }));
  }

  // Tanqueros efectivos de la fila: lo que haya escrito el usuario, o los que
  // asigno el optimizador. Nunca negativo.
  function camionesFor(fields: DispatchFields) {
    return Math.max(0, Math.floor(Number(fields.camiones) || 0));
  }

  // Toneladas DERIVADAS: tanqueros x viajes por tanquero x capacidad por
  // tanquero. La capacidad es fija (32 t por defecto, configurable en Flota),
  // asi que cambiar los tanqueros mueve las toneladas y no al reves.
  function toneladasFor(stop: DistributionPlan["stops"][number], fields: DispatchFields) {
    return camionesFor(fields) * stop.viajesPorCamion * fleet.toneladasPorUnidad;
  }

  // Costo estimado del despacho = costo ref. (km × $/km) de la ruta partida→destino
  // por el numero de viajes, que ahora sale de los tanqueros editados.
  function costoFor(stop: DistributionPlan["stops"][number], fields: DispatchFields) {
    const viajes = camionesFor(fields) * stop.viajesPorCamion;
    return Math.round(routeCostRef(fields.partida || stop.origen, fields.destino || refineryName) * viajes);
  }

  // Filas del optimizador + las que el usuario añadio desde las sugerencias de
  // la IA. Las añadidas van al final y NO pasaron por el MILP.
  // Base de la tabla. Con un plan aprobado manda lo GUARDADO, no lo que acabe
  // de calcular el optimizador: el plan del dia ya se decidio y el optimizador
  // puede dar otro resultado si el inventario cambio desde entonces.
  const baseStops = approvedStops ?? plan.stops;
  const allStops = [...baseStops, ...extras];
  const esAñadida = (index: number) => index >= baseStops.length;

  const orders = allStops.map((stop, index) => {
    const fields = fieldsFor(stop, index);
    return {
      stop,
      fields,
      camiones: camionesFor(fields),
      toneladas: toneladasFor(stop, fields),
      costo: costoFor(stop, fields)
    };
  });

  const costoTotal = orders.reduce((total, order) => total + order.costo, 0);
  const camionesTotal = orders.reduce((total, order) => total + order.camiones, 0);
  const toneladasTotal = orders.reduce((total, order) => total + order.toneladas, 0);

  // Tarjetas de la IA que ninguna fila reclamo: la IA propuso ese despacho y el
  // optimizador no lo incluyo. Se listan aparte para poder auditar la
  // diferencia y, si corresponde, añadirlas al plan. Recorre allStops, asi que
  // una sugerencia añadida desaparece de esta lista.
  const cardsUsadas = new Set<AiCard>();
  allStops.forEach((stop) => {
    const card = findAiCard(aiCards, stop.origen, stop.producto);
    if (card) cardsUsadas.add(card);
  });
  const cardsFueraDelPlan = aiCards.filter((card) => !cardsUsadas.has(card));

  // Veredicto adversarial IA vs MILP. Los cuatro desacuerdos posibles:
  //   coincide  la IA propone esa fila con el mismo tonelaje
  //   difiere   la propone con otro tonelaje
  //   omite     la IA NO la propone (solo cuenta si la revision ya corrio)
  //   añade     la IA propone algo que el plan no tiene (cardsFueraDelPlan)
  const veredictos = allStops.map((stop, index) => {
    if (!reviewDone) return "sin-revision" as const;
    const card = findAiCard(aiCards, stop.origen, stop.producto);
    if (!card) return "omite" as const;
    const sugeridas = aiToneladas(card);
    return sugeridas !== null && sugeridas !== orders[index].toneladas ? ("difiere" as const) : ("coincide" as const);
  });

  const cuenta = {
    coincide: veredictos.filter((v) => v === "coincide").length,
    difiere: veredictos.filter((v) => v === "difiere").length,
    omite: veredictos.filter((v) => v === "omite").length,
    añade: cardsFueraDelPlan.length
  };
  const hayDesacuerdo = cuenta.difiere + cuenta.omite + cuenta.añade > 0;

  // Valida el plan COMPLETO (filas del MILP + añadidas a mano) contra las mismas
  // restricciones que respeta el optimizador. Las filas del MILP siempre pasan;
  // los avisos aparecen por lo añadido a mano o por toneladas editadas.
  //
  // Se usan los valores EFECTIVOS (derivados de los tanqueros editados), no los
  // que calculo el optimizador: subir tanqueros a mano tambien rompe cupos.
  const toneladasEfectivas = (index: number) => orders[index]?.toneladas ?? 0;
  const camionesEfectivos = (index: number) => orders[index]?.camiones ?? 0;

  const estacionDe = (producto: string) =>
    stations.find((station) => station.productos.some((p) => normalize(p) === normalize(producto))) ?? null;

  // Aviso por fila: producto sin estacion o ruta deshabilitada.
  const avisosPorFila = allStops.map((stop, index) => {
    const problemas: string[] = [];
    if (!estacionDe(stop.producto)) {
      problemas.push(`el producto no está asignado a ninguna estación de recepción`);
    }
    if (enabledSources.size > 0 && !enabledSources.has(stop.origen)) {
      problemas.push(`la ruta ${stop.origen} → ${refineryName} está deshabilitada`);
    }
    if (camionesEfectivos(index) <= 0) {
      problemas.push("no tiene tanqueros asignados");
    }
    return problemas;
  });

  // Avisos globales: cupo de tanqueros por estacion y capacidad libre de la
  // refineria por producto. Se acumulan sobre TODAS las filas, porque el cupo lo
  // consume el plan entero, no cada fila por separado.
  const avisosGlobales: string[] = [];

  const camionesPorEstacion = new Map<string, number>();
  allStops.forEach((stop, index) => {
    const estacion = estacionDe(stop.producto);
    if (!estacion) return;
    camionesPorEstacion.set(estacion.id, (camionesPorEstacion.get(estacion.id) ?? 0) + camionesEfectivos(index));
  });
  stations.forEach((station) => {
    const usados = camionesPorEstacion.get(station.id) ?? 0;
    if (usados > station.tankers) {
      avisosGlobales.push(
        `${station.nombre}: ${format(usados)} tanqueros asignados sobre un cupo de ${format(station.tankers)}`
      );
    }
  });

  const toneladasPorProducto = new Map<string, number>();
  allStops.forEach((stop, index) => {
    const key = normalize(stop.producto);
    toneladasPorProducto.set(key, (toneladasPorProducto.get(key) ?? 0) + toneladasEfectivas(index));
  });
  Object.entries(refineryFree).forEach(([producto, libre]) => {
    const asignadas = toneladasPorProducto.get(normalize(producto)) ?? 0;
    if (asignadas > libre) {
      avisosGlobales.push(
        `${producto}: ${format(asignadas)} t asignadas sobre ${format(libre)} t libres en la refinería`
      );
    }
  });

  if (toneladasTotal > plan.capacidadDiaria) {
    avisosGlobales.push(
      `${format(toneladasTotal)} t superan la capacidad diaria de la flota (${format(plan.capacidadDiaria)} t)`
    );
  }

  const totalAvisos = avisosGlobales.length + avisosPorFila.filter((lista) => lista.length > 0).length;

  // Si cambian los incumplimientos, se retira la confirmacion: no vale aceptar
  // unos avisos y aprobar con otros distintos.
  useEffect(() => {
    setOverrideAvisos(false);
  }, [totalAvisos]);

  function añadirSugerencia(card: AiCard) {
    const stop = stopFromCard(card, fleet);
    if (!stop) return;
    setExtras((prev) => [...prev, stop]);
  }

  function quitarAñadida(index: number) {
    const posicion = index - baseStops.length;
    setExtras((prev) => prev.filter((_, i) => i !== posicion));
  }

  const fechaTexto = new Date().toLocaleDateString("es-EC", {
    year: "numeric",
    month: "long",
    day: "numeric"
  });

  // Cuerpo del correo (mailto, texto plano). Redactado legible en cualquier fuente
  // (sin tabla ASCII que se rompe en clientes con fuente proporcional). Sin costo
  // ni estacion (la estacion es una restriccion interna del solver).
  function buildPlainText() {
    const lines = orders.map(({ stop, fields, camiones, toneladas }, index) => {
      return [
        `${index + 1}. ${fields.partida || stop.origen}  ->  ${fields.destino || refineryName}`,
        `   Producto: ${stop.producto}`,
        `   Tanqueros: ${format(camiones)}   Toneladas: ${format(toneladas)} t`
      ].join("\n");
    });
    return [
      `ORDEN DE DESPACHO - ${fechaTexto}`,
      "",
      lines.join("\n\n"),
      "",
      `Total: ${format(camionesTotal)} camiones · ${format(toneladasTotal)} t`
    ].join("\n");
  }

  // Abre el cliente de correo del usuario (mailto) con la orden ya redactada.
  // Sin destinatario fijo: el usuario elige a quien enviarla en su cliente.
  function openMailto() {
    const asunto = encodeURIComponent(`Orden de despacho - ${fechaTexto}`);
    const cuerpo = encodeURIComponent(buildPlainText());
    window.location.href = `mailto:?subject=${asunto}&body=${cuerpo}`;
  }

  // Guarda el plan en Supabase y lo cuenta como transportado (refresca el KPI
  // "Inventario transportado" via onApproved).
  //
  // Es la misma operacion para aprobar y para guardar una edicion: la unica
  // diferencia es que al editar se manda replacePlanId para que el servidor
  // borre la version anterior. Siempre se genera un plan_id nuevo, asi el
  // reemplazo es insertar-y-luego-borrar y nunca queda un hueco sin datos.
  async function savePlan(replacePlanId: string | null) {
    if (orders.length === 0) return;
    const editando = replacePlanId !== null;
    setApproving(true);
    setStatus(editando ? "Guardando cambios…" : "Aprobando plan…");
    try {
      const planId = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`;
      const fecha = new Date().toISOString().slice(0, 10);
      const stops = orders.map(({ stop, fields, camiones, toneladas, costo }) => ({
        plan_id: planId,
        fecha,
        partida: fields.partida || stop.origen,
        destino: fields.destino || refineryName,
        producto: stop.producto,
        tanque: stop.tanque,
        toneladas,
        camiones,
        viajes_por_camion: stop.viajesPorCamion,
        costo,
        occupancy: stop.occupancy,
        acidez: stop.acidez
      }));
      const response = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(replacePlanId ? { stops, replacePlanId } : { stops })
      });
      const data = await response.json();
      if (data.ok) {
        setApprovedPlanId(planId);
        setEditing(false);
        // Lo guardado pasa a ser la base de la tabla. Las claves de `edits` no
        // cambian: stopKey usa el indice global, que se conserva al mover las
        // añadidas de `extras` a la base.
        setApprovedStops(allStops);
        setExtras([]);
        setSavedState({ edits, extras: [] });
        // Ya refleja este plan: evita que el refresco de /api/plan lo rehidrate.
        hydratedPlanId.current = planId;
        setStatus(
          data.warning
            ? data.warning
            : editando
              ? `Plan actualizado: ${format(data.toneladas)} t registradas como transportadas.`
              : `Plan aprobado: ${format(data.toneladas)} t registradas como transportadas.`
        );
        onApproved();
      } else {
        setStatus(data.message ?? "No se pudo guardar el plan.");
      }
    } catch {
      setStatus("Error de red al guardar el plan.");
    } finally {
      setApproving(false);
    }
  }

  // Borra de Supabase el plan aprobado y devuelve la tarjeta a estado editable.
  async function deletePlan() {
    if (!approvedPlanId) return;
    const ok = window.confirm(
      "Se eliminarán de Supabase los despachos de este plan aprobado y dejarán de contar como transportados. ¿Continuar?"
    );
    if (!ok) return;
    setApproving(true);
    setStatus("Eliminando plan…");
    try {
      const response = await fetch("/api/plan", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planId: approvedPlanId })
      });
      const data = await response.json();
      if (data.ok) {
        setApprovedPlanId(null);
        setEditing(false);
        setSavedState(null);
        // Vuelve a mandar el optimizador y se descartan los valores editados.
        setApprovedStops(null);
        setEdits({});
        setExtras([]);
        setStatus(`Plan eliminado: se borraron ${format(data.registros)} despacho(s).`);
        onApproved();
      } else {
        setStatus(data.message ?? "No se pudo eliminar el plan.");
      }
    } catch {
      setStatus("Error de red al eliminar el plan.");
    } finally {
      setApproving(false);
    }
  }

  // Cancelar la edicion descarta lo tocado y restaura lo que hay en Supabase.
  function cancelEdit() {
    if (savedState) {
      setEdits(savedState.edits);
      setExtras(savedState.extras);
    }
    setEditing(false);
    setStatus("Se descartaron los cambios; el plan quedó como estaba aprobado.");
  }

  const busy = approving;

  return (
    <div className="card">
      <div className="section-title">
        <div>
          <h3>Plan de distribución diario</h3>
          <p className="section-note">
            Límite = capacidad de recepción por estación. El optimizador asignó {format(plan.camionesUsados)}{" "}
            tanqueros ({format(plan.toneladasTotales)} t) · costo ${format(plan.costoTotal)}
            {extras.length > 0 && (
              <>
                , más <strong>{extras.length}</strong> despacho{extras.length > 1 ? "s" : ""} añadido
                {extras.length > 1 ? "s" : ""} desde las sugerencias de la IA
              </>
            )}
. Se editan los <strong>tanqueros</strong>: las toneladas se recalculan solas a{" "}
            {format(fleet.toneladasPorUnidad)} t por tanquero. Aprueba y abre la orden en tu correo.
          </p>
        </div>
        <button
          className="btn"
          onClick={reviewPlan}
          disabled={reviewLoading}
          title="Pide a la IA que revise críticamente este plan"
        >
          <Bot size={16} /> {reviewLoading ? "Revisando…" : reviewDone ? "Revisar de nuevo" : "Revisar con IA"}
        </button>
      </div>
      {allStops.length === 0 && cardsFueraDelPlan.length === 0 ? (
        <div className="empty-state">No hay orígenes con inventario disponible para despachar.</div>
      ) : (
        <>
          {/* Estado del plan frente a Supabase: sin esto la tarjeta se veia
              igual antes y despues de aprobar. */}
          {approved && (
            <div className={`plan-state${editing ? " editing" : ""}`}>
              {editing ? (
                <>
                  <Pencil size={16} />
                  <span>
                    <strong>Editando un plan aprobado.</strong> Al guardar se reemplaza en Supabase la versión
                    anterior; si cancelas, vuelve como estaba.
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 size={16} />
                  <span>
                    <strong>Plan aprobado y guardado en Supabase.</strong> Está en solo lectura: usa Editar
                    para cambiarlo o Eliminar para retirarlo del acumulado transportado.
                  </span>
                </>
              )}
            </div>
          )}
          {!reviewDone ? (
            <p className="section-note">
              El plan lo calcula el optimizador. Pulsa <strong>Revisar con IA</strong> para contrastarlo con
              lo que propondría el analista.
            </p>
          ) : (
            <div className={`ai-verdict${hayDesacuerdo ? " warn" : " ok"}`}>
              <Bot size={16} />
              <span>
                La IA <strong>coincide en {cuenta.coincide} de {allStops.length}</strong> despachos
                {cuenta.difiere > 0 && <>, cambiaría <strong>{cuenta.difiere}</strong></>}
                {cuenta.omite > 0 && <>, omitiría <strong>{cuenta.omite}</strong></>}
                {cuenta.añade > 0 && <>, añadiría <strong>{cuenta.añade}</strong></>}.
                {!hayDesacuerdo && " Sin objeciones al plan del optimizador."}
              </span>
            </div>
          )}
          <div className="table-wrap">
            <table className="dispatch-table">
              <thead>
                <tr>
                  <th>Partida</th>
                  <th>Producto</th>
                  <th>Tanqueros</th>
                  <th>Toneladas</th>
                  <th>Destino</th>
                  <th>Costo estimado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {allStops.map((stop, index) => {
                  const key = stopKey(stop, index);
                  const fields = fieldsFor(stop, index);
                  // El MILP decide el despacho; la IA solo aporta el porque.
                  const card = findAiCard(aiCards, stop.origen, stop.producto);
                  const sugeridas = aiToneladas(card);
                  // Se compara contra las toneladas efectivas (derivadas de los
                  // tanqueros editados), no contra las que asigno el optimizador.
                  const efectivas = toneladasFor(stop, fields);
                  const difiere = sugeridas !== null && sugeridas !== efectivas;
                  const añadida = esAñadida(index);
                  return (
                    <Fragment key={key}>
                    <tr className={añadida ? "row-added" : undefined}>
                      <td>
                        {locked ? (
                          fields.partida
                        ) : (
                          <input
                            className="cell-input"
                            value={fields.partida}
                            onChange={(event) => update(key, fields, "partida", event.target.value)}
                          />
                        )}
                      </td>
                      <td>{stop.producto}</td>
                      <td>
                        {locked ? (
                          format(camionesFor(fields))
                        ) : (
                          <input
                            className="cell-input cell-input--num"
                            type="number"
                            min={0}
                            step={1}
                            value={fields.camiones}
                            onChange={(event) => update(key, fields, "camiones", event.target.value)}
                          />
                        )}
                      </td>
                      {/* Derivado, no editable: tanqueros x viajes x capacidad por tanquero. */}
                      <td className="cell-derived" title={`${format(camionesFor(fields))} tanquero(s) × ${stop.viajesPorCamion} viaje(s) × ${format(fleet.toneladasPorUnidad)} t`}>
                        {format(toneladasFor(stop, fields))} t
                      </td>
                      <td>
                        {locked ? (
                          fields.destino
                        ) : (
                          <input
                            className="cell-input"
                            value={fields.destino}
                            onChange={(event) => update(key, fields, "destino", event.target.value)}
                          />
                        )}
                      </td>
                      <td>${format(costoFor(stop, fields))}</td>
                      <td>
                        {añadida && !locked && (
                          <button
                            className="icon-btn"
                            onClick={() => quitarAñadida(index)}
                            title="Quitar del plan"
                            aria-label="Quitar del plan"
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </td>
                    </tr>
                    {(card || añadida || veredictos[index] === "omite") && (
                      <tr className="ai-note-row">
                        <td colSpan={7}>
                          <div className={`ai-note${veredictos[index] === "omite" ? " warn" : ""}`}>
                            {card && <span className={`pill ${priorityPill(card.priority)}`}>{card.priority}</span>}
                            {añadida ? (
                              <span className="ai-flag warn">Añadida por IA · sin validar</span>
                            ) : veredictos[index] === "omite" ? (
                              <span className="ai-flag warn">IA la omitiría</span>
                            ) : (
                              <span className={`ai-flag ${difiere ? "warn" : "ok"}`}>
                                {difiere ? "IA difiere" : "IA coincide"}
                              </span>
                            )}
                            <span className="ai-note-text">
                              {añadida && (
                                <>
                                  No pasó por el optimizador: no se verificó cupo de estación, capacidad libre
                                  de la refinería ni que la ruta esté habilitada.{" "}
                                </>
                              )}
                              {veredictos[index] === "omite" && (
                                <>
                                  La IA no incluyó este despacho en su propuesta. El optimizador sí lo asignó,
                                  así que respeta las restricciones; revisa si su criterio te convence.
                                </>
                              )}
                              {card?.motivo && <>Motivo: {card.motivo}. </>}
                              {card?.riesgo && <>Riesgo: {card.riesgo}.</>}
                              {difiere && (
                                <>
                                  {" "}
                                  <strong>
                                    La IA sugiere {format(sugeridas!)} t; el plan asigna {format(efectivas)} t.
                                  </strong>
                                </>
                              )}
                            </span>
                          </div>
                        </td>
                      </tr>
                    )}
                    {avisosPorFila[index].length > 0 && (
                      <tr className="ai-note-row">
                        <td colSpan={7}>
                          <div className="ai-note warn">
                            <AlertTriangle size={15} />
                            <span className="ai-note-text">{avisosPorFila[index].join("; ")}.</span>
                          </div>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={2}>Total</td>
                  <td>{format(camionesTotal)}</td>
                  <td>{format(toneladasTotal)} t</td>
                  <td />
                  <td>${format(costoTotal)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          {cardsFueraDelPlan.length > 0 && (
            <div className="ai-orphans">
              <h4>Sugerido por la IA, fuera del plan</h4>
              <p className="section-note">
                El optimizador no incluyó estos despachos. Suele deberse a una restricción que la IA no
                respetó: cupo de tanqueros de la estación agotado, producto sin estación asignada, ruta
                deshabilitada o falta de capacidad libre en la refinería.
              </p>
              <ul>
                {cardsFueraDelPlan.map((card, index) => (
                  <li key={`${card.title}-${index}`}>
                    <button
                      className="btn ghost btn-sm"
                      onClick={() => añadirSugerencia(card)}
                      disabled={aiToneladas(card) === null || locked}
                      title={
                        locked
                          ? "El plan está aprobado: pulsa Editar para modificarlo"
                          : aiToneladas(card) === null
                            ? "La sugerencia no indica toneladas"
                            : "Añadir este despacho al plan"
                      }
                    >
                      <Plus size={14} /> Añadir
                    </button>
                    <span className={`pill ${priorityPill(card.priority)}`}>{card.priority}</span>
                    <span className="ai-note-text">
                      <strong>{card.title}</strong>
                      {card.detail && <> · {card.detail}</>}
                      {card.motivo && <> · Motivo: {card.motivo}</>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {totalAvisos > 0 && (
            <div className="plan-warnings">
              <h4>
                <AlertTriangle size={16} /> El plan incumple {totalAvisos} restricción
                {totalAvisos > 1 ? "es" : ""}
              </h4>
              {avisosGlobales.length > 0 && (
                <ul>
                  {avisosGlobales.map((aviso) => (
                    <li key={aviso}>{aviso}</li>
                  ))}
                </ul>
              )}
              <p className="section-note">
                Puede venir de un despacho añadido a mano, de tanqueros editados, o de que el optimizador
                asignó menos carga de la que cabe en esos tanqueros: como las toneladas se derivan de
                tanqueros completos, la fila queda por encima de lo que él calculó. Bajar un tanquero en las
                filas marcadas suele resolverlo.
              </p>
              {!locked && (
                <label className="warn-ack">
                  <input
                    type="checkbox"
                    checked={overrideAvisos}
                    onChange={(event) => setOverrideAvisos(event.target.checked)}
                  />
                  Entiendo los riesgos y quiero aprobar el plan igualmente
                </label>
              )}
            </div>
          )}
          <div className="dispatch-send">
            <div className="dispatch-actions">
              {/* Tres estados excluyentes: sin aprobar (Aprobar), aprobado y
                  bloqueado (Editar / Eliminar) y aprobado en edicion (Guardar /
                  Cancelar). El plan guardado nunca se puede volver a aprobar:
                  eso duplicaba las filas en Supabase. */}
              {locked ? (
                <>
                  <button className="btn" onClick={() => setEditing(true)} disabled={busy}>
                    <Pencil size={16} /> Editar
                  </button>
                  <button className="btn danger" onClick={deletePlan} disabled={busy}>
                    <Trash2 size={16} /> {approving ? "Eliminando…" : "Eliminar"}
                  </button>
                </>
              ) : editing ? (
                <>
                  <button
                    className="btn primary"
                    onClick={() => savePlan(approvedPlanId)}
                    // Misma exigencia que al aprobar: lo editado tampoco se
                    // guarda sin contrastarlo con la IA. Editar cambia los
                    // tanqueros, asi que la revision anterior ya no describe
                    // este plan.
                    disabled={busy || !reviewDone || (totalAvisos > 0 && !overrideAvisos)}
                    title={
                      !reviewDone
                        ? "Pulsa «Revisar con IA» antes de guardar: falta contrastar el plan"
                        : totalAvisos > 0 && !overrideAvisos
                          ? "Confirma que aceptas los incumplimientos para poder guardar"
                          : "Reemplaza en Supabase el plan aprobado"
                    }
                  >
                    <CheckCircle2 size={16} /> {approving ? "Guardando…" : "Guardar cambios"}
                  </button>
                  <button className="btn" onClick={cancelEdit} disabled={busy}>
                    Cancelar
                  </button>
                </>
              ) : (
                <button
                  className="btn primary"
                  onClick={() => savePlan(null)}
                  // Un plan no se aprueba sin contrastarlo antes con la IA: la
                  // revision es la que marca en que despachos se aparta del
                  // optimizador, y aprobar sin verlo desperdicia ese control.
                  disabled={busy || !reviewDone || (totalAvisos > 0 && !overrideAvisos)}
                  title={
                    !reviewDone
                      ? "Pulsa «Revisar con IA» antes de aprobar: falta contrastar el plan"
                      : totalAvisos > 0 && !overrideAvisos
                        ? "Confirma que aceptas los incumplimientos para poder aprobar"
                        : undefined
                  }
                >
                  <CheckCircle2 size={16} /> {approving ? "Aprobando…" : "Aprobar plan"}
                </button>
              )}
              {/* El motivo del bloqueo, visible: un boton apagado sin explicacion
                  se lee como que la app esta rota. */}
              {!locked && !reviewDone && (
                <span className="dispatch-hint">
                  <Bot size={15} />
                  {reviewLoading
                    ? "Revisando el plan con la IA…"
                    : `Falta la revisión con IA para poder ${editing ? "guardar" : "aprobar"}.`}
                </span>
              )}
              {approved && (
                <button className="btn mailto-btn" onClick={openMailto} title="Abrir la orden en tu cliente de correo">
                  <Mail size={16} /> Abrir en correo
                </button>
              )}
            </div>
          </div>
          {status && <p className="section-note dispatch-status">{status}</p>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grafo del pipeline. Describe lo que la app hace DE VERDAD, no una
// arquitectura multiagente: hay un optimizador determinista (MILP) y UNA sola
// llamada a un LLM. Si el pipeline cambia, este grafo hay que actualizarlo a
// mano: no se deriva del codigo.
// ---------------------------------------------------------------------------
type PipelineNode = {
  id: string;
  label: string;
  sub: string;
  kind: "fuente" | "proceso" | "llm" | "salida";
  detalle: string;
  archivo: string;
  x: number;
  y: number;
};

const NODE_W = 190;
const NODE_H = 80;

const PIPELINE_NODES: PipelineNode[] = [
  {
    id: "inventario",
    label: "Inventario",
    sub: "Supabase",
    kind: "fuente",
    detalle:
      "Snapshots diarios por tanque: capacidad, disponible, acidez, tránsito. Se leen paginados porque PostgREST corta en 1.000 filas.",
    archivo: "src/app/api/inventory/route.ts",
    x: 30,
    y: 24
  },
  {
    id: "datos-maestros",
    label: "Datos maestros",
    sub: "Supabase",
    kind: "fuente",
    detalle:
      "Matriz de rutas (km, $/km, on/off), estaciones de recepción con su cupo de tanqueros, y la flota compartida.",
    archivo: "src/app/api/{routes,stations,settings}/route.ts",
    x: 285,
    y: 24
  },
  {
    id: "datos-demo",
    label: "Datos demo",
    sub: "Respaldo local",
    kind: "fuente",
    detalle:
      "Mock de 3 fechas que se usa solo si Supabase no responde o está vacía. El badge del gráfico indica cuál está activo.",
    archivo: "src/lib/sample-data.ts",
    x: 540,
    y: 24
  },
  {
    id: "optimizador",
    label: "Optimizador",
    sub: "MILP determinista",
    kind: "proceso",
    detalle:
      "Maximiza toneladas priorizando acidez del top 25%, minimizando costo. Restricciones: cupo de tanqueros por estación, capacidad libre de la refinería, disponible por origen y rutas habilitadas.",
    archivo: "src/lib/optimizer.ts",
    x: 285,
    y: 156
  },
  {
    id: "analista-ia",
    label: "Analista IA",
    sub: "Hugging Face Router",
    kind: "llm",
    detalle:
      "Única llamada a un LLM. Recibe el plan ya resuelto más el contexto operativo y devuelve prioridades con motivo y riesgo. No decide el plan: lo explica y lo anota.",
    archivo: "src/app/api/ai/route.ts",
    x: 540,
    y: 288
  },
  {
    id: "plan",
    label: "Plan diario",
    sub: "Revisable y editable",
    kind: "proceso",
    detalle:
      "Tabla de despachos. Se editan los tanqueros y las toneladas se derivan. Se pueden añadir sugerencias de la IA que el optimizador descartó, y el plan se valida contra las restricciones antes de aprobar.",
    archivo: "src/app/page.tsx · DistributionPlanCard",
    x: 285,
    y: 420
  },
  {
    id: "aprobacion",
    label: "Aprobación",
    sub: "Persiste en Supabase",
    kind: "salida",
    detalle:
      "Guarda los despachos aprobados y alimenta el acumulado de toneladas transportadas y el histórico de camiones y costo.",
    archivo: "src/app/api/plan/route.ts",
    x: 140,
    y: 552
  },
  {
    id: "notificaciones",
    label: "Notificaciones",
    sub: "Correo · Telegram",
    kind: "salida",
    detalle: "La orden de despacho se abre en el cliente de correo, o se envía por bot de Telegram.",
    archivo: "src/app/api/{email,telegram}/route.ts",
    x: 430,
    y: 552
  }
];

const PIPELINE_EDGES: Array<{ from: string; to: string; label?: string }> = [
  { from: "inventario", to: "optimizador" },
  { from: "datos-maestros", to: "optimizador", label: "restricciones" },
  { from: "datos-demo", to: "optimizador", label: "si no hay datos" },
  { from: "optimizador", to: "plan" },
  { from: "optimizador", to: "analista-ia", label: "plan como contexto" },
  { from: "analista-ia", to: "plan", label: "motivo y riesgo" },
  { from: "plan", to: "aprobacion" },
  { from: "plan", to: "notificaciones" }
];

// Formatos compactos para que quepan dentro del nodo.
function ms(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

function usd(value: number) {
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function PipelineGraph({ dataSource, metrics }: { dataSource: DataSource; metrics: ProcessMetrics[] }) {
  const [selected, setSelected] = useState<string>("optimizador");
  const nodeById = new Map(PIPELINE_NODES.map((node) => [node.id, node]));
  const activo = nodeById.get(selected) ?? PIPELINE_NODES[0];
  const metricsById = new Map(metrics.map((item) => [item.proceso, item]));
  const metricaActiva = metricsById.get(activo.id) ?? null;
  const costoTotal = metrics.reduce((total, item) => total + item.costoTotal, 0);

  const width = 760;
  const height = 664;

  // Flujo VERTICAL: la arista sale del borde inferior del nodo origen y entra
  // por el borde superior del destino. Los puntos de control son verticales,
  // asi la curva arranca y termina en vertical y se lee de arriba hacia abajo.
  function pathFor(from: PipelineNode, to: PipelineNode) {
    const x1 = from.x + NODE_W / 2;
    const y1 = from.y + NODE_H;
    const x2 = to.x + NODE_W / 2;
    const y2 = to.y;
    const mid = (y1 + y2) / 2;
    return `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`;
  }

  return (
    <div className="card">
      <div className="section-title">
        <div>
          <h3>Cómo funciona esta app</h3>
          <p className="section-note">
            Pipeline real: de dónde salen los datos, quién decide el plan y qué hace la IA. Toca un nodo para
            ver el detalle.
          </p>
        </div>
        <span className={`source-badge ${dataSource === "supabase" ? "live" : ""}`}>
          {dataSource === "supabase" ? "Supabase" : "Datos demo"}
        </span>
      </div>

      <div className="graph-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Grafo del pipeline de la aplicación">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="graph-arrow" />
            </marker>
          </defs>

          {PIPELINE_EDGES.map((edge) => {
            const from = nodeById.get(edge.from)!;
            const to = nodeById.get(edge.to)!;
            const activa = edge.from === selected || edge.to === selected;
            // Etiqueta en el punto medio REAL del tramo (origen y destino), no
            // sobre el eje del destino: varias aristas llegan al mismo nodo y
            // sus etiquetas se apilarian en la misma coordenada.
            const midX = (from.x + to.x) / 2 + NODE_W / 2;
            const midY = (from.y + NODE_H + to.y) / 2;
            return (
              <g key={`${edge.from}-${edge.to}`} className={`graph-edge${activa ? " active" : ""}`}>
                <path d={pathFor(from, to)} markerEnd="url(#arrow)" />
                {edge.label && (
                  <text x={midX + 8} y={midY + 4} textAnchor="start">
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          {PIPELINE_NODES.map((node) => (
            <g
              key={node.id}
              className={`graph-node ${node.kind}${node.id === selected ? " selected" : ""}`}
              onClick={() => setSelected(node.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") setSelected(node.id);
              }}
              tabIndex={0}
              role="button"
              aria-pressed={node.id === selected}
            >
              <rect x={node.x} y={node.y} width={NODE_W} height={NODE_H} rx="10" />
              <text x={node.x + 14} y={node.y + 24} className="graph-node-label">
                {node.label}
              </text>
              <text x={node.x + 14} y={node.y + 42} className="graph-node-sub">
                {node.sub}
              </text>
              {(() => {
                const m = metricsById.get(node.id);
                if (!m) return null;
                return (
                  <text x={node.x + 14} y={node.y + 66} className="graph-node-metric">
                    {ms(m.p50Ms)} · {m.exitoPct.toFixed(1)}% · {usd(m.costoTotal)}
                  </text>
                );
              })()}
            </g>
          ))}
        </svg>
      </div>

      <div className="graph-detail">
        <div className="graph-detail-head">
          <span className={`graph-tag ${activo.kind}`}>{activo.kind}</span>
          <h4>{activo.label}</h4>
        </div>
        <p>{activo.detalle}</p>

        {metricaActiva ? (
          <div className="graph-metrics">
            <div>
              <span>Latencia p50 / p95</span>
              <strong>
                {ms(metricaActiva.p50Ms)} / {ms(metricaActiva.p95Ms)}
              </strong>
            </div>
            <div>
              <span>Ejecuciones (30 d)</span>
              <strong>{format(metricaActiva.ejecuciones)}</strong>
            </div>
            <div>
              <span>Tasa de éxito</span>
              <strong className={metricaActiva.exitoPct < 97 ? "warn" : undefined}>
                {metricaActiva.exitoPct.toFixed(2)}%
              </strong>
            </div>
            <div>
              <span>Costo (30 d)</span>
              <strong>{usd(metricaActiva.costoTotal)}</strong>
            </div>
            <div>
              <span>Costo por corrida</span>
              <strong>{usd(metricaActiva.costoPorCorrida)}</strong>
            </div>
            {metricaActiva.tokensIn > 0 && (
              <div>
                <span>Tokens in / out</span>
                <strong>
                  {format(metricaActiva.tokensIn)} / {format(metricaActiva.tokensOut)}
                </strong>
              </div>
            )}
          </div>
        ) : (
          <p className="section-note">
            Sin métricas para este proceso. Ejecuta <code>supabase/seed-metrics.sql</code> para cargar datos de
            ejemplo.
          </p>
        )}

        <code>{activo.archivo}</code>
      </div>

      {metrics.length > 0 && (
        <p className="section-note graph-foot">
          Métricas <strong>ficticias</strong> de los últimos 30 días · costo total del pipeline{" "}
          <strong>{usd(costoTotal)}</strong>. El p95 mostrado es el del peor día de la ventana, no un
          percentil recalculado: no se puede derivar de agregados diarios.
        </p>
      )}
    </div>
  );
}

function InventoryTable({ rows, compact = false }: { rows: InventoryRow[]; compact?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Tipo</th>
            <th>Ubicación</th>
            <th>Producto</th>
            {!compact && <th>Tanque</th>}
            <th>Capacidad</th>
            <th>Inv. neto</th>
            <th>Acidez</th>
            <th>Pendiente</th>
            <th>Tránsito</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.fecha}-${row.nombre}-${row.tanque}-${row.producto}`}>
              <td>{row.tipo}</td>
              <td>{row.nombre}</td>
              <td>{row.producto}</td>
              {!compact && <td>{row.tanque}</td>}
              <td>{format(row.capacidad)}</td>
              <td>{format(row.disponible)}</td>
              <td>
                <span className={`pill ${row.acidez > 4 ? "risk" : row.acidez > 3 ? "warn" : "ok"}`}>
                  {row.acidez.toFixed(1)}
                </span>
              </td>
              <td>{format(row.pendienteRetiro)}</td>
              <td>{format(row.transito + row.importaciones)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Temas sugeridos del chat: preguntas listas para pulsar, sin escribir. Cada
// una se apoya en datos que buildAiContext YA envia, asi que el modelo puede
// responderlas sin inventar. Editar esta lista es la forma de cambiar el chat.
const CHAT_TOPICS: Array<{ label: string; question: string }> = [
  {
    label: "¿Por qué este plan y no otro?",
    question:
      "Explica el plan de distribucion que viene en distributionPlan: por que esos origenes y no otros, que llena cada estacion, y como pesaron la acidez, el costo de ruta y el cupo de recepcion."
  },
  {
    label: "¿Qué me está frenando hoy?",
    question:
      "Identifica el cuello de botella de hoy: cupos de tanqueros por estacion, capacidad libre de la refineria por producto y origenes bloqueados por rutas deshabilitadas. Di cual es el limite que mas aprieta y que se ganaria si se relajara."
  },
  {
    label: "¿Dónde tengo riesgo por acidez?",
    question:
      "Que ubicaciones tienen la acidez mas alta y cuanto tiempo pueden esperar antes de comprometer la calidad. Indica el riesgo concreto de no despacharlas hoy."
  },
  {
    label: "¿Dónde se me va el costo?",
    question:
      "Analiza el costo de transporte: que rutas son las mas caras por tonelada, cuanto pesa cada una en el costo total del plan y que alternativa habria dentro de las rutas habilitadas."
  },
  {
    label: "¿Hay espacio para lo que viene?",
    question:
      "Compara el material entrante por producto (proveedores, importaciones y transito) contra la capacidad libre de la refineria y del puerto. Di si algo llegara sin donde almacenarse y que despachar para liberar espacio."
  },
  {
    label: "¿Y si tengo 20 tanqueros menos?",
    question:
      "Si hoy la flota tuviera 20 tanqueros menos, que despachos del plan mantendrias y cuales sacrificarias, y que consecuencia tendria en acidez y en el material entrante."
  },
  {
    label: "Resume el día en 3 líneas",
    question:
      "Resume la operacion de hoy en exactamente 3 lineas para un reporte a gerencia: situacion del inventario, que se despacha y cual es el principal riesgo."
  }
];

// El estado guarda la PREGUNTA completa que se envio; para el encabezado se
// prefiere la etiqueta corta del tema. Si vino del campo libre no hay etiqueta.
function tituloTema(question: string) {
  if (!question) return "Respuesta";
  return CHAT_TOPICS.find((item) => item.question === question)?.label ?? "Consulta libre";
}

function FloatingChat({
  answer,
  topic,
  loading,
  dataSource,
  onAsk
}: {
  answer: string;
  topic: string;
  loading: boolean;
  dataSource: DataSource;
  onAsk: (question: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [texto, setTexto] = useState("");
  const isDemo = dataSource === "demo";

  // Abrir el panel NO consulta nada: solo muestra los temas. Cada clic en un
  // tema es una inferencia, asi que el gasto lo decide el usuario.
  function enviar(pregunta: string) {
    const limpia = pregunta.trim();
    if (!limpia || loading || isDemo) return;
    onAsk(limpia);
  }

  return (
    <div className="floating-priorities">
      {open && (
        <div className="fp-panel" role="dialog" aria-label="Asistente operativo">
          <div className="fp-header">
            <div>
              <h3>Asistente operativo</h3>
              <span className="fp-sub">{isDemo ? "Vista previa · datos demo" : "Con el contexto de hoy"}</span>
            </div>
            {topic && (
              <button
                className="fp-close"
                onClick={() => enviar(topic)}
                disabled={loading || isDemo}
                aria-label="Repetir la consulta"
                title="Repetir la consulta"
              >
                <RefreshCw size={16} />
              </button>
            )}
            <button className="fp-close" onClick={() => setOpen(false)} aria-label="Cerrar">
              <X size={18} />
            </button>
          </div>

          <div className="fp-body">
            {isDemo && (
              <div className="fp-demo-note">
                Vista previa con datos de ejemplo: no hay snapshots de inventario en Supabase.
              </div>
            )}

            <div className="fp-topics">
              {CHAT_TOPICS.map((item) => (
                <button
                  key={item.label}
                  className={`fp-topic${topic === item.question ? " active" : ""}`}
                  onClick={() => enviar(item.question)}
                  disabled={loading || isDemo}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {(loading || answer) && (
              <div className="fp-ai">
                {/* El titulo repite el tema consultado: sin esto la respuesta
                    aparece huerfana y no se ve a que pregunta contesta. */}
                <div className="fp-ai-title">
                  <Sparkles size={15} /> {tituloTema(topic)}
                </div>
                <div className="fp-ai-body">
                  {loading
                    ? "Consultando con IA..."
                    : answer.split("\n").map((linea, index) => (
                        <p key={index} className="fp-ai-line">
                          {linea}
                        </p>
                      ))}
                </div>
              </div>
            )}

            <form
              className="fp-ask"
              onSubmit={(event) => {
                event.preventDefault();
                enviar(texto);
                setTexto("");
              }}
            >
              <input
                value={texto}
                onChange={(event) => setTexto(event.target.value)}
                placeholder="O escribe tu propia consulta"
                disabled={loading || isDemo}
              />
              <button className="btn primary btn-sm" type="submit" disabled={loading || isDemo || !texto.trim()}>
                Enviar
              </button>
            </form>
          </div>
        </div>
      )}
      <button
        className="fp-fab"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Asistente operativo"
        title="Asistente operativo"
      >
        <Bot size={22} />
      </button>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: ReactNode; label: string }) {
  return (
    <button className={active ? "active" : ""} onClick={onClick} title={label}>
      {icon} <span className="nav-label">{label}</span>
    </button>
  );
}

function Kpi({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="card kpi">
      <span>{icon}</span>
      <strong>{value}</strong>
      <small>{label}</small>
    </div>
  );
}

function viewTitle(view: View) {
  if (view === "rutas") return "Plan de distribución diario";
  if (view === "datos") return "Datos maestros";
  if (view === "ia") return "Arquitectura y pipeline";
  return "Inventario";
}

function viewSubtitle(view: View) {
  if (view === "rutas") return "Despacho del día por acidez, costo y capacidad de recepción, con histórico de aprobados.";
  if (view === "datos") return "Flota, matriz de rutas y estaciones de recepción que alimentan el plan.";
  if (view === "ia") return "De dónde salen los datos, quién decide el plan y qué papel cumple la IA.";
  return "";
}

function format(value: number) {
  return Math.round(value).toLocaleString("es-EC");
}

type AiCard = {
  priority: "crítica" | "alta" | "media" | "baja";
  title: string;
  detail: string;
  motivo: string;
  riesgo: string;
};

// Empareja una fila del plan con la tarjeta que la IA escribio para ese mismo
// despacho. El criterio es origen + producto: el titulo de la tarjeta es el
// origen y el producto aparece en el detalle ("DESTINO, PRODUCTO, N t").
// Se compara con normalize() para tolerar acentos y mayusculas.
function findAiCard(cards: AiCard[], origen: string, producto: string) {
  const o = normalize(origen);
  const p = normalize(producto);
  return (
    cards.find((card) => normalize(card.title).includes(o) && normalize(card.detail).includes(p)) ?? null
  );
}

// Toneladas que sugirio la IA en esa tarjeta, si las menciona. Sirve para
// contrastarlas con las del MILP; el plan sigue mandando, esto solo se muestra.
function aiToneladas(card: AiCard | null) {
  if (!card) return null;
  const match = card.detail.match(/([\d.,]+)\s*t\b/i);
  if (!match) return null;
  // Formato es-EC: 1.234,5 -> quitar separador de miles y normalizar decimal.
  const value = Number(match[1].replace(/\./g, "").replace(",", "."));
  return Number.isFinite(value) && value > 0 ? Math.round(value) : null;
}

function priorityPill(priority: string) {
  return priority === "alta" || priority === "crítica" ? "risk" : priority === "media" ? "warn" : "ok";
}

// Convierte el texto del Analisis IA (vinetas "Prioridad <nivel>: <origen> -> <producto>,
// <tons> a <estacion>. Motivo: ... Riesgo: ...") en tarjetas. Tolerante a variaciones; las
// lineas sin prioridad se omiten salvo "Accion inmediata", que se devuelve como footer.
// Convierte la respuesta de la IA en tarjetas. NUNCA descarta contenido: lo que
// no encaja en el formato de tarjeta se devuelve en `extras` y se muestra tal
// cual debajo. Antes las lineas no reconocidas se tiraban en silencio, y la
// respuesta se leia incompleta aunque el modelo la hubiera generado entera.
function parseAiCards(text: string): { cards: AiCard[]; footer: string; extras: string[] } {
  const cards: AiCard[] = [];
  const extras: string[] = [];
  let footer = "";
  if (!text) return { cards, footer, extras };

  for (const raw of text.split(/\r?\n+/)) {
    const line = raw.replace(/^[\s\-*•▪·]+/, "").replace(/^\d+[.)]\s*/, "").trim();
    if (!line) continue;

    if (/^acci[oó]n inmediata\s*:/i.test(line)) {
      footer = line.replace(/^acci[oó]n inmediata\s*:\s*/i, "").trim();
      continue;
    }

    // Tolerante con la forma del prefijo: "Prioridad alta:", "Alta:",
    // "Prioridad: alta -", "[ALTA]"... El modelo no siempre respeta el formato
    // pedido, y una variacion de puntuacion no deberia costar una tarjeta.
    const match = line.match(/^\[?\s*(?:prioridad\s*:?\s*)?(cr[ií]tica|alta|media|baja)\s*\]?\s*[:.\-–—]\s*/i);
    if (!match) {
      extras.push(line);
      continue;
    }
    const priority = (match[1].toLowerCase().startsWith("cr") ? "crítica" : match[1].toLowerCase()) as AiCard["priority"];
    const rest = line.slice(match[0].length).trim();

    // Titulo = origen (antes de "->"); si no hay flecha, primera clausula antes de coma.
    const arrow = rest.indexOf("->");
    let title: string;
    let body: string;
    if (arrow > 0) {
      title = rest.slice(0, arrow).trim();
      body = rest.slice(arrow + 2).trim();
    } else {
      const comma = rest.indexOf(",");
      title = (comma > 0 ? rest.slice(0, comma) : rest).trim();
      body = comma > 0 ? rest.slice(comma + 1).trim() : rest;
    }

    // Separar Motivo / Riesgo del detalle principal.
    const motivo = (body.match(/motivo\s*:\s*([^]*?)(?=\s*riesgo\s*:|$)/i)?.[1] ?? "").trim().replace(/\.\s*$/, "");
    const riesgo = (body.match(/riesgo\s*:\s*([^]*)$/i)?.[1] ?? "").trim().replace(/\.\s*$/, "");
    const detail = body.split(/\s*motivo\s*:/i)[0].trim().replace(/[.,;\s]*$/, "");

    cards.push({ priority, title: title || "Sugerencia", detail, motivo, riesgo });
  }

  return { cards, footer, extras };
}

function buildInventoryHistory(rows: InventoryRow[]) {
  const grouped = new Map<string, { date: string; stock: number; transito: number; capacidad: number }>();

  rows.forEach((row) => {
    const date = normalizeDate(row.fecha) || "Sin fecha";
    const current = grouped.get(date) ?? { date, stock: 0, transito: 0, capacidad: 0 };
    if (row.tanque) {
      // Stock fisico en tanque (disponible: refineria/puerto no llenan INVENTARIO).
      current.stock += row.disponible;
      current.capacidad += row.capacidad;
    } else {
      // Tipos de suministro: cada uno llena solo su columna
      // (TRANSITO->transito, IMPORTACIONES->importaciones, PROVEEDORES->pendienteRetiro).
      current.transito += row.transito + row.importaciones + row.pendienteRetiro;
    }
    grouped.set(date, current);
  });

  return Array.from(grouped.values()).sort((a, b) => comparableDate(a.date) - comparableDate(b.date));
}

// Colapsa el historico de planes aprobados a un punto por mes SUMANDO. A
// diferencia del inventario (un stock, que se promedia), los despachos son un
// flujo: camiones, costo y toneladas POR DIA. El total del mes es lo que
// significa algo ("en marzo se movieron N camiones y costo $X"); promediarlos
// daria otra metrica distinta.
function toMonthlyApproved(daily: DailyApproved[]): DailyApproved[] {
  if (daily.length === 0) return daily;
  // Anio de la fecha mas reciente, misma convencion que filterCurrentYear.
  const year = daily[daily.length - 1].fecha.slice(0, 4);
  const grouped = new Map<string, DailyApproved>();

  daily.forEach((point) => {
    const month = monthKey(point.fecha);
    if (!month || !month.startsWith(year)) return;
    const current = grouped.get(month) ?? { fecha: month, camiones: 0, costo: 0, toneladas: 0 };
    current.camiones += point.camiones;
    current.costo += point.costo;
    current.toneladas += point.toneladas;
    grouped.set(month, current);
  });

  return Array.from(grouped.values()).sort((a, b) => a.fecha.localeCompare(b.fecha));
}

// Clave de mes (YYYY-MM) de una fecha canonica. null si el valor no es una
// fecha real ("Sin fecha"), para que no invente un mes.
function monthKey(date: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date.slice(0, 7) : null;
}

// Colapsa el historico diario a un punto por mes, PROMEDIANDO los dias con dato.
// El inventario es un stock: sumar los dias del mes daria un numero sin sentido
// (30 dias x ~7.600 t). El promedio es el nivel medio de stock del mes.
function toMonthlyHistory(daily: ReturnType<typeof buildInventoryHistory>) {
  const grouped = new Map<string, { date: string; stock: number; transito: number; capacidad: number; dias: number }>();

  daily.forEach((point) => {
    const month = monthKey(point.date);
    if (!month) return;
    const current = grouped.get(month) ?? { date: month, stock: 0, transito: 0, capacidad: 0, dias: 0 };
    current.stock += point.stock;
    current.transito += point.transito;
    current.capacidad += point.capacidad;
    current.dias += 1;
    grouped.set(month, current);
  });

  return Array.from(grouped.values())
    .map(({ date, stock, transito, capacidad, dias }) => ({
      date,
      stock: dias > 0 ? stock / dias : 0,
      transito: dias > 0 ? transito / dias : 0,
      capacidad: dias > 0 ? capacidad / dias : 0
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// Mismo criterio para el heatmap: promedio mensual de disponible y capacidad
// por ubicacion, y la ocupacion se recalcula sobre esos promedios (no es el
// promedio de porcentajes, que ponderaria mal los dias sin dato).
function toMonthlyHeatmap(heatmap: ReturnType<typeof buildLocationHeatmap>) {
  const months = Array.from(
    new Set(heatmap.dates.map(monthKey).filter((month): month is string => month !== null))
  ).sort((a, b) => a.localeCompare(b));

  const locations = heatmap.locations.map((location) => {
    const byMonth = new Map<string, { disponible: number; capacidad: number; dias: number }>();

    location.cells.forEach((cell) => {
      // occupancy null = esa ubicacion no reporto ese dia; no cuenta para el promedio.
      if (cell.occupancy === null) return;
      const month = monthKey(cell.date);
      if (!month) return;
      const current = byMonth.get(month) ?? { disponible: 0, capacidad: 0, dias: 0 };
      current.disponible += cell.disponible;
      current.capacidad += cell.capacidad;
      current.dias += 1;
      byMonth.set(month, current);
    });

    return {
      nombre: location.nombre,
      cells: months.map((month) => {
        const acc = byMonth.get(month);
        if (!acc || acc.dias === 0 || acc.capacidad === 0) {
          return { date: month, occupancy: null, disponible: 0, capacidad: 0 };
        }
        const disponible = acc.disponible / acc.dias;
        const capacidad = acc.capacidad / acc.dias;
        return { date: month, occupancy: disponible / capacidad, disponible, capacidad };
      })
    };
  });

  return { dates: months, locations };
}

function buildLocationHeatmap(rows: InventoryRow[]) {
  const dateOrder = new Map<string, number>();
  const byLocation = new Map<string, Map<string, { disponible: number; capacidad: number }>>();

  rows.forEach((row) => {
    // Solo ubicaciones con tanque fisico; los tipos de suministro no se grafican.
    if (!row.tanque) return;
    const date = normalizeDate(row.fecha) || "Sin fecha";
    dateOrder.set(date, comparableDate(date));
    const series = byLocation.get(row.nombre) ?? new Map();
    const cell = series.get(date) ?? { disponible: 0, capacidad: 0 };
    cell.disponible += row.disponible;
    cell.capacidad += row.capacidad;
    series.set(date, cell);
    byLocation.set(row.nombre, series);
  });

  const dates = Array.from(dateOrder.keys()).sort((a, b) => (dateOrder.get(a) ?? 0) - (dateOrder.get(b) ?? 0));

  const locations = Array.from(byLocation.entries())
    .map(([nombre, series]) => ({
      nombre,
      cells: dates.map((date) => {
        const cell = series.get(date);
        const occupancy = cell && cell.capacidad > 0 ? cell.disponible / cell.capacidad : null;
        return { date, occupancy, disponible: cell?.disponible ?? 0, capacidad: cell?.capacidad ?? 0 };
      })
    }))
    .sort((a, b) => {
      const aRefinery = normalize(a.nombre) === normalize(refineryName);
      const bRefinery = normalize(b.nombre) === normalize(refineryName);
      if (aRefinery !== bRefinery) return aRefinery ? -1 : 1;
      return a.nombre.localeCompare(b.nombre, "es");
    });

  return { dates, locations };
}

function heatColor(occupancy: number) {
  const t = Math.max(0, Math.min(1, occupancy));
  const stops: Array<{ p: number; c: [number, number, number] }> = [
    { p: 0, c: [240, 246, 233] },
    { p: 0.6, c: [125, 179, 91] },
    { p: 1, c: [63, 125, 69] }
  ];

  let lower = stops[0];
  let upper = stops[stops.length - 1];
  for (let index = 0; index < stops.length - 1; index += 1) {
    if (t >= stops[index].p && t <= stops[index + 1].p) {
      lower = stops[index];
      upper = stops[index + 1];
      break;
    }
  }

  const span = upper.p - lower.p || 1;
  const ratio = (t - lower.p) / span;
  const channel = (index: number) => Math.round(lower.c[index] + (upper.c[index] - lower.c[index]) * ratio);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

function heatTextColor(occupancy: number) {
  return occupancy > 0.55 ? "#ffffff" : "#1f2520";
}

function getLatestInventoryRows(rows: InventoryRow[]) {
  // Cada ubicacion/entidad (nombre) se actualiza en fechas distintas: la
  // refineria llega a una fecha mas nueva que extractoras o proveedores.
  // Por eso se toma la fecha mas reciente DE CADA ubicacion y se conservan
  // TODAS sus filas de ese dia: todos los tanques de un sitio y todos los
  // lotes de un proveedor (que puede tener varios el mismo dia).
  const latestTsByName = new Map<string, number>();

  for (const row of rows) {
    const ts = rowTimestamp(row.fecha);
    const current = latestTsByName.get(row.nombre);
    if (current === undefined || ts > current) {
      latestTsByName.set(row.nombre, ts);
    }
  }

  return rows.filter((row) => rowTimestamp(row.fecha) === latestTsByName.get(row.nombre));
}

function filterRecentDays(rows: InventoryRow[], days: number) {
  // Ventana de escala fija anclada a la fecha mas reciente presente en los datos
  // (no a "hoy": los snapshots cargados pueden ser historicos). Inclusiva de N dias.
  if (rows.length === 0) return rows;
  const maxTs = Math.max(...rows.map((row) => rowTimestamp(row.fecha)));
  const cutoff = maxTs - (days - 1) * 86_400_000;
  return rows.filter((row) => rowTimestamp(row.fecha) >= cutoff);
}

// Filas del anio de la fecha mas reciente presente en los datos. Se ancla a los
// datos y no a "hoy" por la misma razon que filterRecentDays: el historico
// cargado puede no llegar hasta la fecha actual.
function filterCurrentYear(rows: InventoryRow[]) {
  if (rows.length === 0) return rows;
  const maxTs = Math.max(...rows.map((row) => rowTimestamp(row.fecha)));
  if (maxTs < 0) return rows;
  const year = new Date(maxTs).getUTCFullYear();
  return rows.filter((row) => {
    const ts = rowTimestamp(row.fecha);
    return ts >= 0 && new Date(ts).getUTCFullYear() === year;
  });
}

function rowTimestamp(value: string) {
  const parsed = new Date(normalizeDate(value)).getTime();
  return Number.isNaN(parsed) ? -1 : parsed;
}

function normalizeDate(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  const parsed = new Date(trimmed);
  if (!Number.isNaN(parsed.getTime())) return parsed.toISOString().slice(0, 10);
  return trimmed;
}

function comparableDate(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? Number.MAX_SAFE_INTEGER : parsed;
}

function shortDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  // La fecha canonica (YYYY-MM-DD) es el dia UTC; se formatea en UTC para no
  // retroceder un dia al renderizar en zonas horarias negativas (Ecuador UTC-5).
  return parsed.toLocaleDateString("es-EC", { day: "2-digit", month: "short", timeZone: "UTC" });
}

// Etiquetas de eje/tooltip segun granularidad: en mensual las claves son
// YYYY-MM y shortDate/longDate las interpretarian como el dia 1 del mes.
function bucketShortLabel(value: string, granularity: Granularity) {
  if (granularity !== "mensual") return shortDate(value);
  const parsed = new Date(`${value}-01T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("es-EC", { month: "short", timeZone: "UTC" });
}

function bucketLongLabel(value: string, granularity: Granularity) {
  if (granularity !== "mensual") return longDate(value);
  const parsed = new Date(`${value}-01T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("es-EC", { month: "long", year: "numeric", timeZone: "UTC" });
}

function longDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("es-EC", { day: "2-digit", month: "long", year: "numeric", timeZone: "UTC" });
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function normalize(value: string) {
  return value.trim().toUpperCase();
}

function routeKey(origen: string, destino: string) {
  return `${origen}|||${destino}`;
}

// Normaliza una estacion cruda (Supabase / localStorage) al tipo Station.
function normalizeStation(raw: unknown): Station {
  const record = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(record.id ?? `est-${Math.random().toString(36).slice(2)}`),
    nombre: String(record.nombre ?? "Estación"),
    tankers: Number(record.tankers) || 0,
    productos: Array.isArray(record.productos) ? record.productos.map(String) : []
  };
}
