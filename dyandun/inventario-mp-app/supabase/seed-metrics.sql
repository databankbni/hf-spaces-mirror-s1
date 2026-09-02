-- ============================================================================
-- SEED DE METRICAS FICTICIAS de los procesos del pipeline.
--
-- Ejecutar en Supabase: Dashboard -> SQL Editor -> New query -> pegar -> Run.
-- Requiere schema.sql (crea inventario_mp_app_process_metrics).
--
-- 30 dias x 8 procesos = 240 filas, terminando HOY. Alimenta las metricas de
-- desempeño, calidad y costo del grafo de la pestaña IA.
--
-- SON DATOS FICTICIOS: los valores son plausibles pero inventados. Cuando se
-- instrumente el codigo de verdad, este seed se reemplaza por escrituras reales
-- y la UI no cambia (lee lo mismo desde /api/metrics).
--
-- IDEMPOTENTE: unique (proceso, fecha) + upsert.
-- REVERTIR: delete from inventario_mp_app_process_metrics;
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Perfil de cada proceso. `proceso` DEBE coincidir con el id del nodo en
-- PIPELINE_NODES (src/app/page.tsx) o la metrica no se muestra.
--
--   base_ejec   ejecuciones/dia tipicas
--   p50 / p95   latencia base en ms
--   fallo_ppm   fallos por cada 1000 ejecuciones (calidad)
--   costo_mil   costo en USD por cada 1000 ejecuciones
--
-- Los numeros reflejan la naturaleza de cada proceso: las lecturas a Supabase
-- son frecuentes y baratas, el MILP es local (costo cero, latencia variable) y
-- el LLM es el unico con costo por token y latencia de segundos.
-- ----------------------------------------------------------------------------
with perfil (proceso, base_ejec, p50, p95, fallo_ppm, costo_mil, es_llm) as (
  values
    ('inventario',      420, 180::numeric,  520::numeric,  4::numeric, 0.00::numeric, false),
    ('datos-maestros',  380,  95::numeric,  240::numeric,  3::numeric, 0.00::numeric, false),
    ('datos-demo',       12,   2::numeric,    6::numeric,  0::numeric, 0.00::numeric, false),
    ('optimizador',     260,  42::numeric,  118::numeric,  1::numeric, 0.00::numeric, false),
    ('analista-ia',      34, 2600::numeric, 7400::numeric, 62::numeric, 1850.00::numeric, true),
    ('plan',            260,  18::numeric,   55::numeric,  0::numeric, 0.00::numeric, false),
    ('aprobacion',       26, 310::numeric,  780::numeric,  9::numeric, 0.00::numeric, false),
    ('notificaciones',   18, 640::numeric, 1900::numeric, 31::numeric, 0.00::numeric, false)
),
dias as (
  select
    g.dia::date                                            as fecha,
    (g.dia::date - (current_date - 29))                    as i
  from generate_series((current_date - 29)::timestamp, current_date::timestamp, interval '1 day') as g(dia)
),
base as (
  select
    d.fecha,
    d.i,
    p.proceso,
    p.p50,
    p.p95,
    p.fallo_ppm,
    p.costo_mil,
    p.es_llm,
    -- Fin de semana al ~35%: casi no se opera. Mas un ciclo de 11 dias que
    -- evita que todos los dias laborables se vean identicos.
    greatest(
      1,
      round(
        p.base_ejec
        * (case when extract(isodow from d.fecha) in (6, 7) then 0.35 else 1.0 end)
        * (1 + 0.15 * sin(2 * pi() * (d.i::double precision) / 11.0))::numeric
      )
    )::int as ejecuciones,
    -- La latencia sube cuando hay mas carga: ciclo de 7 dias, +-22%.
    (1 + 0.22 * sin(2 * pi() * ((d.i + 3)::double precision) / 7.0))::numeric as factor_lat
  from dias d
  cross join perfil p
)
insert into inventario_mp_app_process_metrics (
  proceso, fecha, ejecuciones, exitos, duracion_p50_ms, duracion_p95_ms,
  costo_usd, tokens_in, tokens_out, updated_at
)
select
  proceso,
  fecha,
  ejecuciones,
  -- Calidad: los fallos escalan con el volumen, con al menos 1 fallo el dia que
  -- toque para que la tasa de exito no salga siempre 100% clavado.
  greatest(0, ejecuciones - round(ejecuciones * fallo_ppm / 1000.0)::int) as exitos,
  round(p50 * factor_lat)::int                                            as duracion_p50_ms,
  round(p95 * factor_lat)::int                                            as duracion_p95_ms,
  round(ejecuciones * costo_mil / 1000.0, 4)                              as costo_usd,
  -- Tokens solo del LLM: ~4.200 de contexto y ~380 de respuesta por llamada.
  case when es_llm then ejecuciones * 4200 else 0 end                     as tokens_in,
  case when es_llm then ejecuciones *  380 else 0 end                     as tokens_out,
  now()
from base
on conflict (proceso, fecha) do update set
  ejecuciones     = excluded.ejecuciones,
  exitos          = excluded.exitos,
  duracion_p50_ms = excluded.duracion_p50_ms,
  duracion_p95_ms = excluded.duracion_p95_ms,
  costo_usd       = excluded.costo_usd,
  tokens_in       = excluded.tokens_in,
  tokens_out      = excluded.tokens_out,
  updated_at      = now();


-- ============================================================================
-- VERIFICACION: resumen de 30 dias por proceso, igual que lo que mostrara la UI.
-- ============================================================================
select
  proceso,
  count(*)                                                     as dias,
  sum(ejecuciones)                                             as ejecuciones,
  round(100.0 * sum(exitos) / nullif(sum(ejecuciones), 0), 2)  as exito_pct,
  round(avg(duracion_p50_ms))                                  as p50_ms,
  max(duracion_p95_ms)                                         as p95_ms,
  round(sum(costo_usd), 2)                                     as costo_usd,
  round(sum(costo_usd) / nullif(sum(ejecuciones), 0), 6)       as costo_por_corrida
from inventario_mp_app_process_metrics
group by proceso
order by costo_usd desc, proceso;
