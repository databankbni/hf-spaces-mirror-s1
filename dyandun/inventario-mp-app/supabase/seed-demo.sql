-- ============================================================================
-- SEED DE DATOS FICTICIOS (DEMO) para inventario-mp-app.
--
-- Ejecutar en Supabase: Dashboard -> SQL Editor -> New query -> pegar -> Run.
-- Requiere que schema.sql ya se haya ejecutado (crea las 5 tablas).
--
-- Siembra lo que la app lee de Supabase, para que la demo tenga datos
-- PERSISTENTES (viven en la base, no en localStorage):
--   A) inventario_mp_app_routes             -> matriz de rutas (km, $/km, on/off)
--   B) inventario_mp_app_stations           -> estaciones de recepcion
--   C) inventario_mp_app_settings ('fleet') -> flota compartida
--   D) inventario_mp_app_approved_dispatches-> planes aprobados del anio en curso
--
-- Los snapshots de inventario van en un script aparte: seed-inventory.sql.
--
-- IDEMPOTENTE: se puede ejecutar las veces que haga falta. Las rutas,
-- estaciones y settings son upserts; los despachos demo se borran y se
-- vuelven a generar (ver la marca 'DEMO-' mas abajo).
--
-- REVERTIR el demo sin tocar datos reales:
--   delete from inventario_mp_app_approved_dispatches where placas like 'DEMO-%';
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Marca de datos demo.
--
-- La columna `placas` existe en el esquema pero la app NUNCA la escribe
-- (approve() en src/app/page.tsx no la incluye). La usamos como marca: todas
-- las filas sembradas aqui llevan placas 'DEMO-...'. Asi el borrado de abajo
-- limpia SOLO el demo y respeta cualquier plan aprobado de verdad desde la UI.
-- ----------------------------------------------------------------------------
delete from inventario_mp_app_approved_dispatches where placas like 'DEMO-%';


-- ============================================================================
-- A) RUTAS
--
-- Los 4 primeros pares replican src/lib/sample-data.ts (mismos km y $/km) para
-- que el merge cliente/servidor de page.tsx no muestre discrepancias.
--
-- CRITICO: `origen` debe coincidir EXACTO y en mayusculas con
-- InventoryRow.nombre, y `destino` = 'DANEC SANGOLQUI'. Si no, enabledSources
-- (src/lib/optimizer.ts) deja ese origen fuera del plan.
--
-- ESMERALDAS va deshabilitada a proposito: demuestra el toggle on/off de la
-- matriz (una ruta en off da costo 0 y no se usa).
-- ============================================================================
insert into inventario_mp_app_routes (origen, destino, km, costo_por_km, enabled, updated_at)
values
  ('QUEVEDO',                'DANEC SANGOLQUI', 250, 1.22, true,  now()),
  ('MANTA',                  'DANEC SANGOLQUI', 390, 1.35, true,  now()),
  ('GUAYAQUIL',              'DANEC SANGOLQUI', 420, 1.28, true,  now()),
  ('SANTO DOMINGO',          'DANEC SANGOLQUI', 115, 1.18, true,  now()),
  ('PROVEEDOR LA CONCORDIA', 'DANEC SANGOLQUI', 180, 1.15, true,  now()),
  ('ESMERALDAS',             'DANEC SANGOLQUI', 310, 1.44, false, now())
on conflict (origen, destino) do update set
  km           = excluded.km,
  costo_por_km = excluded.costo_por_km,
  enabled      = excluded.enabled,
  updated_at   = now();


-- ============================================================================
-- B) ESTACIONES DE RECEPCION
--
-- Los ids son los que genera la app (estacion-1..3) para que un guardado
-- posterior desde la UI haga upsert en vez de duplicar.
--
-- CRITICO: los nombres dentro de `productos` deben coincidir con
-- InventoryRow.producto (la comparacion es via normalize(): mayusculas y sin
-- acentos). Un producto sin estacion queda EXCLUIDO del plan.
--
-- Cupos distintos (6/4/3) para que el cuello de botella del MILP se note.
-- ============================================================================
insert into inventario_mp_app_stations (id, nombre, tankers, productos, posicion, updated_at)
values
  ('estacion-1', 'Estación 1', 6, '["ACEITE ROJO DE PALMA HIBRIDA"]'::jsonb, 0, now()),
  ('estacion-2', 'Estación 2', 4, '["ACEITE DE SOYA"]'::jsonb,               1, now()),
  ('estacion-3', 'Estación 3', 3, '["ACEITE DE PALMISTE PKO"]'::jsonb,       2, now())
on conflict (id) do update set
  nombre     = excluded.nombre,
  tankers    = excluded.tankers,
  productos  = excluded.productos,
  posicion   = excluded.posicion,
  updated_at = now();


-- ============================================================================
-- C) FLOTA COMPARTIDA (settings key='fleet')
--
-- Capacidad diaria = 65 * 32 * 1 = 2.080 t/dia. El volumen sembrado en D) se
-- mantiene por debajo de ese techo para que los numeros sean plausibles.
-- ============================================================================
insert into inventario_mp_app_settings (key, value, updated_at)
values ('fleet', '{"unidades":65,"toneladasPorUnidad":32,"viajesPorDia":1}'::jsonb, now())
on conflict (key) do update set
  value      = excluded.value,
  updated_at = now();


-- ============================================================================
-- D) PLANES APROBADOS DEL ANIO EN CURSO (~1.140 filas)
--
-- Un plan_id distinto por dia (como hace approve(), que genera un uuid por
-- plan) x 5 despachos por dia, del 1 de enero de current_date hasta HOY.
--
-- El rango se recalcula solo en cada ejecucion, igual que seed-inventory.sql.
-- Alimenta el grafico "Camiones y costo" de la pestaña Rutas en sus dos vistas
-- (diaria: ultimos 30 dias; mensual: total por mes) y el KPI acumulado
-- "Inventario transportado".
--
-- Toda la variacion es DETERMINISTA (derivada del dia del año y del indice de
-- la plantilla), nunca random(): el seed debe ser reproducible.
--
-- Formulas replicadas del codigo de la app:
--   toneladas = camiones * viajes_por_camion * toneladasPorUnidad (32)
--   costo     = round(km * costo_por_km * camiones * viajes_por_camion)  <- costoFor() en page.tsx
--   occupancy = FRACCION 0..1 (no porcentaje)
-- ============================================================================
with dias as materialized (
  select
    g.dia::date        as fecha,
    gen_random_uuid()  as plan_id
  from generate_series(
    date_trunc('year', current_date)::timestamp,
    current_date::timestamp,
    interval '1 day'
  ) as g(dia)
),
plantilla (idx, partida, producto, tanque, camiones_base, km, costo_km, acidez_base) as (
  values
    (0, 'QUEVEDO',       'ACEITE ROJO DE PALMA HIBRIDA', 'TK-Q02', 16, 250::numeric, 1.22::numeric, 4.2::numeric),
    (1, 'GUAYAQUIL',     'ACEITE ROJO DE PALMA HIBRIDA', 'TK-G07', 14, 420::numeric, 1.28::numeric, 3.6::numeric),
    (2, 'SANTO DOMINGO', 'ACEITE ROJO DE PALMA HIBRIDA', 'TK-S04', 10, 115::numeric, 1.18::numeric, 4.8::numeric),
    (3, 'MANTA',         'ACEITE DE SOYA',               'TK-M01', 11, 390::numeric, 1.35::numeric, 0.9::numeric),
    (4, 'QUEVEDO',       'ACEITE DE SOYA',               'TK-Q02',  7, 250::numeric, 1.22::numeric, 1.1::numeric)
),
base as (
  select
    d.fecha,
    d.plan_id,
    p.partida,
    p.producto,
    p.tanque,
    p.km,
    p.costo_km,
    p.acidez_base,
    extract(doy from d.fecha)::int as doy,
    p.idx,
    -- Dos escalas, como en seed-inventory.sql:
    --   * fin de semana al ~60%: le da forma a la vista DIARIA.
    --   * ciclo estacional de 120 dias (+-18%): hace que los MESES se
    --     diferencien entre si. Sin el, los totales mensuales solo variarian
    --     por el calendario (28 a 31 dias) y la vista mensual seria casi plana.
    (case when extract(isodow from d.fecha) in (6, 7) then 0.6 else 1.0 end)
      * (1 + 0.18 * sin(2 * pi() * (extract(doy from d.fecha)::double precision) / 120.0))::numeric
      as factor_dia,
    -- Variacion determinista -2..+2 camiones
    ((extract(doy from d.fecha)::int * 7 + p.idx * 13) % 5) - 2 as variacion,
    p.camiones_base
  from dias d
  cross join plantilla p
),
calculado as (
  select
    fecha,
    plan_id,
    partida,
    producto,
    tanque,
    km,
    costo_km,
    doy,
    idx,
    acidez_base,
    greatest(3, round((camiones_base + variacion) * factor_dia)::int) as camiones
  from base
)
insert into inventario_mp_app_approved_dispatches (
  plan_id, approved_at, fecha, partida, destino, producto, tanque,
  toneladas, camiones, viajes_por_camion, placas, costo, occupancy, acidez
)
select
  plan_id,
  fecha + interval '7 hours'                              as approved_at,  -- aprobacion matutina
  fecha,
  partida,
  'DANEC SANGOLQUI'                                       as destino,
  producto,
  tanque,
  camiones * 1 * 32                                       as toneladas,
  camiones,
  1                                                       as viajes_por_camion,
  'DEMO-' || to_char(fecha, 'MMDD') || '-' || idx         as placas,        -- marca de dato demo
  round(km * costo_km * camiones * 1)                     as costo,
  round((0.55 + ((doy * 11 + idx * 7) % 41) / 100.0)::numeric, 2) as occupancy,
  round((acidez_base + ((doy * 3 + idx * 5) % 11) / 10.0 - 0.5)::numeric, 1) as acidez
from calculado;


-- ============================================================================
-- E) VERIFICACION
-- ============================================================================
select
  'despachos demo'                       as concepto,
  count(*)                               as filas,
  count(distinct plan_id)                as planes,
  min(fecha)::text || ' -> ' || max(fecha)::text as rango,
  round(sum(toneladas))                  as toneladas_total,
  round(sum(costo))                      as costo_total
from inventario_mp_app_approved_dispatches
where placas like 'DEMO-%';

-- Lo que devolvera el KPI "Inventario transportado" (incluye despachos reales):
select coalesce(sum(toneladas), 0) as total_transportado, count(*) as registros
from inventario_mp_app_approved_dispatches;

-- Vista MENSUAL del grafico de rutas: TOTAL por mes. A diferencia del
-- inventario (un stock, que se promedia), los despachos son un flujo y lo que
-- significa algo es la suma. Replica toMonthlyApproved() del cliente.
select
  to_char(fecha, 'YYYY-MM') as mes,
  count(distinct fecha)     as dias_con_plan,
  sum(camiones)             as camiones,
  round(sum(toneladas))     as toneladas,
  round(sum(costo))         as costo
from inventario_mp_app_approved_dispatches
group by to_char(fecha, 'YYYY-MM')
order by mes;

select 'rutas'      as tabla, count(*) as filas from inventario_mp_app_routes
union all
select 'estaciones', count(*) from inventario_mp_app_stations
union all
select 'settings',   count(*) from inventario_mp_app_settings;
