import { InventoryRow, RouteCost } from "./types";

const latestSampleInventory: InventoryRow[] = [
  {
    fecha: "2026-05-29",
    tipo: "REFINERIA",
    nombre: "DANEC SANGOLQUI",
    producto: "ACEITE ROJO DE PALMA HIBRIDA",
    tanque: "TK-R01",
    capacidad: 2500,
    inventario: 1420,
    disponible: 1392,
    acidez: 3.1,
    diasRetrazo: 0,
    pedido: 900,
    retirado: 620,
    pendienteRetiro: 280,
    transito: 180,
    importaciones: 0,
    observacion: "Consumo regular de refineria"
  },
  {
    fecha: "2026-05-29",
    tipo: "REFINERIA",
    nombre: "DANEC SANGOLQUI",
    producto: "ACEITE DE SOYA",
    tanque: "TK-R02",
    capacidad: 1500,
    inventario: 920,
    disponible: 900,
    acidez: 0.5,
    diasRetrazo: 0,
    pedido: 0,
    retirado: 0,
    pendienteRetiro: 0,
    transito: 0,
    importaciones: 0,
    observacion: "Tanque de soya"
  },
  {
    fecha: "2026-05-29",
    tipo: "EXTRACTORA",
    nombre: "QUEVEDO",
    producto: "ACEITE ROJO DE PALMA HIBRIDA",
    tanque: "TK-Q02",
    capacidad: 1800,
    inventario: 1650,
    disponible: 1628,
    acidez: 4.9,
    diasRetrazo: 2,
    pedido: 500,
    retirado: 260,
    pendienteRetiro: 240,
    transito: 0,
    importaciones: 0,
    observacion: "Alta ocupacion"
  },
  {
    fecha: "2026-05-29",
    tipo: "EXTRACTORA",
    nombre: "MANTA",
    producto: "ACEITE DE SOYA",
    tanque: "TK-M01",
    capacidad: 1400,
    inventario: 920,
    disponible: 905,
    acidez: 1.8,
    diasRetrazo: 0,
    pedido: 380,
    retirado: 310,
    pendienteRetiro: 70,
    transito: 160,
    importaciones: 420,
    observacion: "Importacion programada"
  },
  {
    fecha: "2026-05-29",
    tipo: "EXTRACTORA",
    nombre: "GUAYAQUIL",
    producto: "ACEITE ROJO DE PALMA HIBRIDA",
    tanque: "TK-G07",
    capacidad: 2200,
    inventario: 1880,
    disponible: 1841,
    acidez: 2.6,
    diasRetrazo: 1,
    pedido: 760,
    retirado: 420,
    pendienteRetiro: 340,
    transito: 80,
    importaciones: 0,
    observacion: "Disponible para despacho"
  },
  {
    fecha: "2026-05-29",
    tipo: "EXTRACTORA",
    nombre: "SANTO DOMINGO",
    producto: "ACEITE ROJO DE PALMA HIBRIDA",
    tanque: "TK-S04",
    capacidad: 1200,
    inventario: 380,
    disponible: 371,
    acidez: 2.2,
    diasRetrazo: 0,
    pedido: 260,
    retirado: 240,
    pendienteRetiro: 20,
    transito: 130,
    importaciones: 0,
    observacion: "Nivel bajo"
  },
  {
    fecha: "2026-05-29",
    tipo: "PROVEEDORES",
    nombre: "PROVEEDOR LA CONCORDIA",
    producto: "ACEITE ROJO DE PALMA HIBRIDA",
    tanque: "",
    capacidad: 0,
    inventario: 0,
    disponible: 0,
    acidez: 0,
    diasRetrazo: 0,
    pedido: 0,
    retirado: 0,
    pendienteRetiro: 320,
    transito: 0,
    importaciones: 0,
    observacion: "Materia prima por retirar"
  }
];

export const sampleInventory: InventoryRow[] = [
  ...buildSampleSnapshot(latestSampleInventory, "2026-05-27", 0.88),
  ...buildSampleSnapshot(latestSampleInventory, "2026-05-28", 0.94),
  ...latestSampleInventory
];

export const sampleRoutes: RouteCost[] = [
  { origen: "QUEVEDO", destino: "DANEC SANGOLQUI", km: 250, costoPorKm: 1.22 },
  { origen: "MANTA", destino: "DANEC SANGOLQUI", km: 390, costoPorKm: 1.35 },
  { origen: "GUAYAQUIL", destino: "DANEC SANGOLQUI", km: 420, costoPorKm: 1.28 },
  { origen: "SANTO DOMINGO", destino: "DANEC SANGOLQUI", km: 115, costoPorKm: 1.18 }
];

function buildSampleSnapshot(rows: InventoryRow[], fecha: string, factor: number): InventoryRow[] {
  return rows.map((row) => ({
    ...row,
    fecha,
    inventario: Math.round(row.inventario * factor),
    disponible: Math.round(row.disponible * factor),
    pedido: Math.round(row.pedido * factor),
    retirado: Math.round(row.retirado * factor),
    pendienteRetiro: Math.round(row.pendienteRetiro * factor),
    transito: Math.round(row.transito * factor),
    importaciones: Math.round(row.importaciones * factor)
  }));
}
