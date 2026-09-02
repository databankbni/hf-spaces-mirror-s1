-- Esquema para persistir los planes de distribucion aprobados.
-- Ejecutar en Supabase: Dashboard -> SQL Editor -> New query -> pegar -> Run.
--
-- Cada fila = un despacho (stop) aprobado del plan diario. Las columnas
-- replican lo que genera el plan (ver DistributionStop en src/lib/types.ts) mas
-- los campos editables de la orden (partida, placas, destino, toneladas).

-- Las tablas usan el prefijo del nombre de la app (inventario_mp_app_) para
-- distinguirlas de otros proyectos en la misma base de Supabase.

create table if not exists inventario_mp_app_approved_dispatches (
  id                uuid primary key default gen_random_uuid(),
  plan_id           uuid not null,                 -- agrupa los stops aprobados juntos
  approved_at       timestamptz not null default now(),
  fecha             date not null default current_date,
  partida           text not null,
  destino           text not null,
  producto          text not null,
  tanque            text,
  toneladas         numeric not null default 0,
  camiones          integer not null default 0,
  viajes_por_camion integer not null default 0,
  placas            text,
  costo             numeric not null default 0,
  occupancy         numeric,
  acidez            numeric
);

-- Para tablas ya creadas antes de agregar el costo estimado:
alter table inventario_mp_app_approved_dispatches add column if not exists costo numeric not null default 0;

create index if not exists inventario_mp_app_approved_dispatches_plan_id_idx
  on inventario_mp_app_approved_dispatches (plan_id);
create index if not exists inventario_mp_app_approved_dispatches_fecha_idx
  on inventario_mp_app_approved_dispatches (fecha);

-- Activa RLS: sin politicas, la llave publishable/anon queda sin acceso (deny
-- por defecto). La app entra solo desde el servidor con la llave secreta
-- (service_role / sb_secret_...), que SALTA RLS, asi que no se necesitan
-- politicas y la tabla queda bloqueada para clientes publicos.
alter table inventario_mp_app_approved_dispatches enable row level security;

-- El acumulado "Inventario transportado" = suma de toneladas:
--   select coalesce(sum(toneladas), 0) as total_transportado from inventario_mp_app_approved_dispatches;
--
-- La app accede SOLO desde rutas server-side (src/app/api/plan/route.ts) con la
-- llave secreta de servidor: service_role clasica (JWT) o la nueva secret key
-- (sb_secret_...). Ambas saltan RLS. La publishable/anon NO sirve para insertar.


-- ============================================================================
-- Matriz de rutas editable: km, $/km y on/off por par origen->destino.
-- Una fila por combinacion origen->destino entre nodos con tanque.
-- ============================================================================

create table if not exists inventario_mp_app_routes (
  id           uuid primary key default gen_random_uuid(),
  origen       text not null,
  destino      text not null,
  km           numeric not null default 0,
  costo_por_km numeric not null default 0,
  enabled      boolean not null default true,
  updated_at   timestamptz not null default now(),
  unique (origen, destino)
);

-- Misma postura de seguridad: RLS sin politicas; acceso solo server-side con la
-- llave secreta (src/app/api/routes/route.ts).
alter table inventario_mp_app_routes enable row level security;


-- ============================================================================
-- Estaciones de recepcion de la refineria (configurables). Cada fila = una
-- estacion: nombre, cupo de tanqueros/dia y la lista de productos que recibe
-- (jsonb). Cuello de botella del plan diario (ver buildDistributionPlan).
-- ============================================================================

create table if not exists inventario_mp_app_stations (
  id          text primary key,
  nombre      text not null,
  tankers     integer not null default 0,
  productos   jsonb not null default '[]'::jsonb,
  posicion    integer not null default 0,
  updated_at  timestamptz not null default now()
);

-- Misma postura de seguridad: RLS sin politicas; acceso solo server-side con la
-- llave secreta (src/app/api/stations/route.ts).
alter table inventario_mp_app_stations enable row level security;


-- ============================================================================
-- Configuraciones sueltas compartidas (clave -> valor JSON). Hoy guarda la
-- flota (key='fleet': numero de transportes y toneladas por transporte) para
-- que todos los usuarios vean la misma informacion. Fuente de verdad compartida.
-- ============================================================================

create table if not exists inventario_mp_app_settings (
  key         text primary key,
  value       jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

-- Misma postura de seguridad: RLS sin politicas; acceso solo server-side con la
-- llave secreta (src/app/api/settings/route.ts).
alter table inventario_mp_app_settings enable row level security;


-- ============================================================================
-- Snapshots diarios de inventario. Una fila = un tanque (o un tipo de
-- suministro sin tanque) en una fecha. Es la UNICA fuente de datos reales de
-- inventario: sin filas aca, la app cae al mock src/lib/sample-data.ts.
--
-- Alimenta el grafico "Historico de inventario" y el mapa de calor por
-- ubicacion: sin varias fechas cargadas, esos graficos quedan con 2-3 puntos.
--
-- Las columnas replican InventoryRow (src/lib/types.ts) en snake_case; el
-- mapeo a camelCase lo hace src/app/api/inventory/route.ts.
-- ============================================================================

create table if not exists inventario_mp_app_inventory (
  id                        uuid primary key default gen_random_uuid(),
  fecha                     date not null,
  tipo                      text not null,                  -- EXTRACTORA | PUERTO | REFINERIA | PROVEEDORES
  nombre                    text not null,                  -- ubicacion; debe calzar con routes.origen
  producto                  text not null,                  -- debe calzar con stations.productos
  tanque                    text not null default '',        -- vacio = tipo de suministro, no stock fisico
  capacidad                 numeric not null default 0,
  inventario                numeric not null default 0,
  disponible                numeric not null default 0,      -- neto despues de merma; es lo que grafica el stock
  acidez                    numeric not null default 0,
  oc                        text,
  orden_recibida_en_bodega  text,
  fecha_orden               date,
  dias_retrazo              integer not null default 0,
  pedido                    numeric not null default 0,
  retirado                  numeric not null default 0,
  pendiente_retiro          numeric not null default 0,
  observacion               text,
  transito                  numeric not null default 0,
  importaciones             numeric not null default 0,
  updated_at                timestamptz not null default now(),
  -- Un snapshot por tanque y fecha: permite reejecutar cargas sin duplicar.
  unique (fecha, nombre, producto, tanque)
);

create index if not exists inventario_mp_app_inventory_fecha_idx
  on inventario_mp_app_inventory (fecha);

-- Misma postura de seguridad: RLS sin politicas; acceso solo server-side con la
-- llave secreta (src/app/api/inventory/route.ts).
alter table inventario_mp_app_inventory enable row level security;


-- ============================================================================
-- Metricas de ejecucion de los procesos del pipeline: desempeño, calidad y
-- costo. Alimenta el grafo de la pestaña IA.
--
-- Se guarda un AGREGADO DIARIO por proceso, no una fila por ejecucion: con
-- miles de corridas al dia, traer las filas crudas para promediarlas en el
-- cliente no escala. 8 procesos x 30 dias = 240 filas.
--
-- `proceso` debe coincidir con el id del nodo en PIPELINE_NODES
-- (src/app/page.tsx): inventario, datos-maestros, datos-demo, optimizador,
-- analista-ia, plan, aprobacion, notificaciones.
--
-- Los percentiles se guardan ya calculados porque no se pueden derivar de otros
-- agregados: el p95 de la semana no es el promedio de los p95 diarios.
-- ============================================================================

create table if not exists inventario_mp_app_process_metrics (
  id               uuid primary key default gen_random_uuid(),
  proceso          text not null,
  fecha            date not null,
  ejecuciones      integer not null default 0,
  exitos           integer not null default 0,      -- calidad: exitos / ejecuciones
  duracion_p50_ms  integer not null default 0,      -- desempeño
  duracion_p95_ms  integer not null default 0,
  costo_usd        numeric not null default 0,      -- costo del dia para ese proceso
  tokens_in        integer not null default 0,      -- solo aplica al analista IA
  tokens_out       integer not null default 0,
  updated_at       timestamptz not null default now(),
  unique (proceso, fecha)
);

create index if not exists inventario_mp_app_process_metrics_fecha_idx
  on inventario_mp_app_process_metrics (fecha);

-- Misma postura de seguridad: RLS sin politicas; acceso solo server-side con la
-- llave secreta (src/app/api/metrics/route.ts).
alter table inventario_mp_app_process_metrics enable row level security;
