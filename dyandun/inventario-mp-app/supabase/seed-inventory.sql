-- ============================================================================
-- SEED DE INVENTARIO FICTICIO (anio en curso) para inventario-mp-app.
--
-- Ejecutar en Supabase: Dashboard -> SQL Editor -> New query -> pegar -> Run.
-- Requiere que schema.sql ya se haya ejecutado (crea inventario_mp_app_inventory).
--
-- Llena el grafico "Historico de inventario" y el mapa de calor por ubicacion,
-- que antes dependian del mock src/lib/sample-data.ts (solo 3 fechas).
--
-- Cubre del 1 de enero del anio en curso hasta HOY (current_date), un snapshot
-- por dia y 8 filas por snapshot. A mediados de agosto son ~228 dias = ~1.824
-- filas, y la vista mensual muestra 8 puntos (ene..ago).
--
-- El rango se recalcula solo en cada ejecucion, asi que la demo nunca se ve
-- vieja ni hay que reeditar fechas.
--
-- IDEMPOTENTE: la tabla tiene unique (fecha, nombre, producto, tanque) y aca se
-- hace upsert sobre esa clave. Reejecutarlo actualiza en vez de duplicar.
--
-- REVERTIR: delete from inventario_mp_app_inventory;
-- (la tabla la escribe solo este seed: /api/inventory es de solo lectura)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Las ubicaciones y productos replican src/lib/sample-data.ts para que calcen
-- con las rutas y estaciones sembradas por seed-demo.sql.
--
-- CRITICO:
--   * `nombre`   debe calzar con inventario_mp_app_routes.origen (mayusculas).
--   * `producto` debe calzar con inventario_mp_app_stations.productos, o el
--     producto queda excluido del plan de distribucion.
--   * la fila sin tanque (PROVEEDOR LA CONCORDIA) es la que alimenta la serie
--     "transito" del grafico: buildInventoryHistory() suma transito +
--     importaciones + pendiente_retiro SOLO en filas sin tanque.
--
-- El movimiento es una suma de sinusoides deterministas (no random()), con dos
-- escalas distintas y a proposito:
--
--   * ciclo corto (21 dias): llenado y vaciado del tanque. Es lo que da forma a
--     la vista DIARIA.
--   * ciclo estacional (~91 dias, trimestral): es lo que hace que los MESES se
--     diferencien entre si. Sin el, promediar por mes cancela el ciclo corto
--     (mes ~= 1,4 ciclos) y la vista mensual saldria casi plana.
--
-- Cada tanque tiene ademas su propio desfase, asi las curvas no suben y bajan
-- todas juntas y el historico se ve como operacion real.
-- ----------------------------------------------------------------------------
with dias as (
  select
    g.dia::date                                            as fecha,
    (g.dia::date - date_trunc('year', current_date)::date) as i
  from generate_series(
    date_trunc('year', current_date)::timestamp,
    current_date::timestamp,
    interval '1 day'
  ) as g(dia)
),
plantilla (idx, tipo, nombre, producto, tanque, capacidad, occ_base, amp, fase, acidez_base) as (
  values
    (0, 'REFINERIA',    'DANEC SANGOLQUI',        'ACEITE ROJO DE PALMA HIBRIDA', 'TK-R01', 2500::numeric, 0.58, 0.16,  0, 3.1),
    (1, 'REFINERIA',    'DANEC SANGOLQUI',        'ACEITE DE SOYA',               'TK-R02', 1500::numeric, 0.62, 0.12,  5, 0.5),
    (2, 'EXTRACTORA',   'QUEVEDO',                'ACEITE ROJO DE PALMA HIBRIDA', 'TK-Q02', 1800::numeric, 0.72, 0.20,  3, 4.6),
    (3, 'EXTRACTORA',   'QUEVEDO',                'ACEITE DE SOYA',               'TK-Q05',  900::numeric, 0.55, 0.18,  9, 1.0),
    (4, 'EXTRACTORA',   'MANTA',                  'ACEITE DE SOYA',               'TK-M01', 1400::numeric, 0.63, 0.17, 12, 1.7),
    (5, 'EXTRACTORA',   'GUAYAQUIL',              'ACEITE ROJO DE PALMA HIBRIDA', 'TK-G07', 2200::numeric, 0.78, 0.15,  6, 2.7),
    (6, 'EXTRACTORA',   'SANTO DOMINGO',          'ACEITE ROJO DE PALMA HIBRIDA', 'TK-S04', 1200::numeric, 0.45, 0.22, 15, 2.3),
    (7, 'PROVEEDORES',  'PROVEEDOR LA CONCORDIA', 'ACEITE ROJO DE PALMA HIBRIDA', '',          0::numeric, 0.00, 0.00,  0, 0.0)
),
onda as (
  select
    d.fecha,
    d.i,
    p.idx,
    p.tipo,
    p.nombre,
    p.producto,
    p.tanque,
    p.capacidad,
    p.acidez_base,
    -- Ocupacion = ciclo corto (21 d, forma la vista diaria)
    --            + ciclo estacional (91 d, separa los meses entre si).
    -- Se acota a [0.05, 0.97] para que nunca supere la capacidad del tanque ni
    -- caiga a negativo cuando ambos ciclos coinciden en el mismo extremo.
    least(0.97, greatest(0.05,
      (p.occ_base
        + p.amp * sin(2 * pi() * ((d.i + p.fase)::double precision) / 21.0)
        + 0.13  * sin(2 * pi() * ((d.i + p.fase * 3)::double precision) / 91.0)
      )::numeric
    )) as ocupacion,
    -- Acidez: ciclo de 13 dias (espera de despacho) + deriva estacional de 121
    -- dias, para que tambien tenga textura al promediar por mes.
    (0.6 * sin(2 * pi() * ((d.i + p.fase)::double precision) / 13.0)
      + 0.5 * sin(2 * pi() * ((d.i + p.fase * 2)::double precision) / 121.0))::numeric as acidez_delta,
    -- Ciclo de 9 dias: ritmo de retiro contra lo pedido.
    (0.5 + 0.3 * sin(2 * pi() * ((d.i + p.fase * 2)::double precision) / 9.0))::numeric      as ratio_retiro
  from dias d
  cross join plantilla p
),
calculado as (
  select
    fecha,
    i,
    tipo,
    nombre,
    producto,
    tanque,
    capacidad,
    ocupacion,
    round(acidez_base + acidez_delta, 1)                          as acidez,
    round(capacidad * ocupacion)                                  as disponible,
    round(capacidad * 0.30)                                       as pedido,
    round(capacidad * 0.30 * ratio_retiro)                        as retirado,
    -- Fila sin tanque: materia prima por retirar en el proveedor. Mismo criterio
    -- que la ocupacion: ciclo corto (17 d) + estacional (105 d), para que la
    -- serie de transito tampoco se aplane al promediar por mes.
    round(
      320
      + 140 * sin(2 * pi() * (i::double precision) / 17.0)::numeric
      +  95 * sin(2 * pi() * (i::double precision) / 105.0)::numeric
    ) as pendiente_proveedor
  from onda
)
insert into inventario_mp_app_inventory (
  fecha, tipo, nombre, producto, tanque, capacidad, inventario, disponible, acidez,
  dias_retrazo, pedido, retirado, pendiente_retiro, observacion, transito, importaciones, updated_at
)
select
  fecha,
  tipo,
  nombre,
  producto,
  tanque,
  capacidad,
  -- El inventario bruto incluye la merma que `disponible` ya descuenta.
  round(disponible * 1.02)                                        as inventario,
  disponible,
  greatest(0.2, acidez)                                           as acidez,
  (i % 4)                                                         as dias_retrazo,
  case when tanque = '' then 0 else pedido end                    as pedido,
  case when tanque = '' then 0 else retirado end                  as retirado,
  case when tanque = '' then pendiente_proveedor
       else greatest(0, pedido - retirado) end                    as pendiente_retiro,
  case
    when tanque = ''        then 'Materia prima por retirar'
    when ocupacion > 0.85   then 'Alta ocupacion'
    when ocupacion < 0.35   then 'Nivel bajo'
    else 'Operacion normal'
  end                                                             as observacion,
  -- Transito solo en tanques (camiones en ruta hacia ese destino).
  case when tanque = '' then 0 else round(capacidad * 0.06) end   as transito,
  -- Importaciones: solo soya por MANTA, cada 15 dias.
  case when nombre = 'MANTA' and i % 15 = 0 then 420 else 0 end   as importaciones,
  now()
from calculado
on conflict (fecha, nombre, producto, tanque) do update set
  tipo             = excluded.tipo,
  capacidad        = excluded.capacidad,
  inventario       = excluded.inventario,
  disponible       = excluded.disponible,
  acidez           = excluded.acidez,
  dias_retrazo     = excluded.dias_retrazo,
  pedido           = excluded.pedido,
  retirado         = excluded.retirado,
  pendiente_retiro = excluded.pendiente_retiro,
  observacion      = excluded.observacion,
  transito         = excluded.transito,
  importaciones    = excluded.importaciones,
  updated_at       = now();


-- ============================================================================
-- VERIFICACION
-- ============================================================================
select
  count(*)                                       as filas,
  count(distinct fecha)                          as fechas,
  min(fecha)::text || ' -> ' || max(fecha)::text as rango,
  count(distinct nombre)                         as ubicaciones,
  count(distinct producto)                       as productos
from inventario_mp_app_inventory;

-- Stock total por fecha (lo que dibuja la vista DIARIA), ultimos 10 dias:
select
  fecha,
  round(sum(disponible) filter (where tanque <> ''))  as stock,
  round(sum(capacidad)  filter (where tanque <> ''))  as capacidad,
  round(sum(transito + importaciones + pendiente_retiro) filter (where tanque = '')) as transito
from inventario_mp_app_inventory
group by fecha
order by fecha desc
limit 10;

-- Vista MENSUAL: promedio de los totales diarios por mes. Replica lo que hace
-- toMonthlyHistory() en el cliente (primero totaliza el dia, despues promedia
-- los dias del mes). Sirve para confirmar que los meses NO salen planos.
with por_dia as (
  select
    fecha,
    sum(disponible) filter (where tanque <> '')                             as stock,
    sum(capacidad)  filter (where tanque <> '')                             as capacidad,
    sum(transito + importaciones + pendiente_retiro) filter (where tanque = '') as transito
  from inventario_mp_app_inventory
  group by fecha
)
select
  to_char(fecha, 'YYYY-MM')      as mes,
  count(*)                       as dias,
  round(avg(stock))              as stock_promedio,
  round(avg(transito))           as transito_promedio,
  round(100 * avg(stock) / nullif(avg(capacidad), 0), 1) as ocupacion_pct
from por_dia
group by to_char(fecha, 'YYYY-MM')
order by mes;
