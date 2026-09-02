export type InventoryRow = {
  fecha: string;
  tipo: string;
  nombre: string;
  producto: string;
  tanque: string;
  capacidad: number;
  inventario: number;
  disponible: number;
  acidez: number;
  oc?: string;
  ordenRecibidaEnBodega?: string;
  fechaOrden?: string;
  diasRetrazo: number;
  pedido: number;
  retirado: number;
  pendienteRetiro: number;
  observacion?: string;
  transito: number;
  importaciones: number;
};

export type FleetInput = {
  unidades: number;
  toneladasPorUnidad: number;
  viajesPorDia: number;
};

export type RouteCost = {
  origen: string;
  destino: string;
  km: number;
  costoPorKm: number;
  enabled?: boolean;
};

// Estacion de recepcion configurable: nombre, cupo de tanqueros/dia y la lista de
// productos (por nombre) que puede recibir. Producto sin estacion = excluido del plan.
export type Station = {
  id: string;
  nombre: string;
  tankers: number;
  productos: string[];
};

export type DistributionStop = {
  origen: string;
  producto: string;
  tanque: string;
  estacion: string;
  occupancy: number;
  acidez: number;
  urgency: number;
  toneladas: number;
  camiones: number;
  viajesPorCamion: number;
  costo: number;
};

export type DistributionPlan = {
  stops: DistributionStop[];
  toneladasTotales: number;
  camionesUsados: number;
  viajesTotales: number;
  capacidadDiaria: number;
  costoTotal: number;
};

export type Recommendation = {
  id: string;
  priority: "alta" | "media" | "baja";
  title: string;
  detail: string;
  suggestedTons: number;
  source: string;
  product: string;
  acidPenalty: number;
  logisticsScore: number;
};
