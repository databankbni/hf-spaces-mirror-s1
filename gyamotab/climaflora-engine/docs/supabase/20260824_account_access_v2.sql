-- ClimaFlora account creation, entitlements and quota enforcement v2.
begin;

-- Hosted Auth and server-generated magic links must both create a profile.
create or replace function public.climaflora_create_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.climaflora_profiles (id, first_name, last_name, display_name, plan, role)
  values (
    new.id,
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'first_name', '')), ''),
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'last_name', '')), ''),
    nullif(trim(coalesce(
      new.raw_user_meta_data ->> 'display_name',
      concat_ws(' ',
        nullif(trim(coalesce(new.raw_user_meta_data ->> 'first_name', '')), ''),
        nullif(trim(coalesce(new.raw_user_meta_data ->> 'last_name', '')), '')
      )
    )), ''),
    'FREE',
    'USER'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke all on function public.climaflora_create_profile() from public, anon, authenticated;

drop trigger if exists climaflora_auth_user_created on auth.users;
create trigger climaflora_auth_user_created
after insert on auth.users
for each row execute function public.climaflora_create_profile();

-- Repair users created before the trigger was reliable.
insert into public.climaflora_profiles (id, first_name, last_name, display_name, plan, role)
select
  u.id,
  nullif(trim(coalesce(u.raw_user_meta_data ->> 'first_name', '')), ''),
  nullif(trim(coalesce(u.raw_user_meta_data ->> 'last_name', '')), ''),
  nullif(trim(coalesce(
    u.raw_user_meta_data ->> 'display_name',
    concat_ws(' ',
      nullif(trim(coalesce(u.raw_user_meta_data ->> 'first_name', '')), ''),
      nullif(trim(coalesce(u.raw_user_meta_data ->> 'last_name', '')), '')
    )
  )), ''),
  'FREE',
  'USER'
from auth.users u
where not exists (select 1 from public.climaflora_profiles p where p.id = u.id);

-- plan is canonical and server-controlled. Webhooks downgrade it when access ends;
-- Sostagora grants are an independent PLUS source; admins receive PRO capabilities.
create or replace function public.climaflora_my_entitlements()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with access as (
    select case
      when p.role = 'ADMIN' then 'PRO'
      when p.plan = 'PRO' then 'PRO'
      when p.plan = 'PLUS' or p.sostagora_access then 'PLUS'
      else 'FREE'
    end as plan
    from public.climaflora_profiles p
    where p.id = (select auth.uid())
  )
  select jsonb_build_object(
    'plan', coalesce(a.plan, 'FREE'),
    'saved_projects', case coalesce(a.plan, 'FREE') when 'PRO' then 250 when 'PLUS' then 10 else 1 end,
    'saved_sites', case coalesce(a.plan, 'FREE') when 'PRO' then 50 when 'PLUS' then 5 else 1 end,
    'comparisons', case coalesce(a.plan, 'FREE') when 'PRO' then 20 when 'PLUS' then 5 else 0 end,
    'monthly_exports', case coalesce(a.plan, 'FREE') when 'PRO' then 100 when 'PLUS' then 10 else 0 end,
    'advanced_scenarios', coalesce(a.plan, 'FREE') in ('PLUS','PRO'),
    'advanced_exports', coalesce(a.plan, 'FREE') = 'PRO',
    'commercial_use', coalesce(a.plan, 'FREE') = 'PRO',
    'palette', coalesce(a.plan, 'FREE') in ('PLUS','PRO')
  )
  from (select 1) seed left join access a on true;
$$;

revoke all on function public.climaflora_my_entitlements() from public, anon;
grant execute on function public.climaflora_my_entitlements() to authenticated, service_role;

create or replace function public.climaflora_has_plus()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select exists (
    select 1 from public.climaflora_profiles p
    where p.id = (select auth.uid())
      and (p.role = 'ADMIN' or p.plan in ('PLUS','PRO') or p.sostagora_access)
  );
$$;

revoke all on function public.climaflora_has_plus() from public, anon;
grant execute on function public.climaflora_has_plus() to authenticated, service_role;

-- Découverte can save one project/site; paid tiers receive larger server-enforced quotas.
drop policy if exists "climaflora plus projects select" on public.climaflora_projects;
drop policy if exists "climaflora plus projects insert" on public.climaflora_projects;
drop policy if exists "climaflora plus projects update" on public.climaflora_projects;
drop policy if exists "climaflora plus projects delete" on public.climaflora_projects;

create policy "climaflora own projects select" on public.climaflora_projects
for select to authenticated using (user_id = (select auth.uid()));
create policy "climaflora own projects insert" on public.climaflora_projects
for insert to authenticated with check (user_id = (select auth.uid()));
create policy "climaflora own projects update" on public.climaflora_projects
for update to authenticated using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));
create policy "climaflora own projects delete" on public.climaflora_projects
for delete to authenticated using (user_id = (select auth.uid()));

create or replace function public.climaflora_enforce_project_quota()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_plan text;
  v_project_limit integer;
  v_site_limit integer;
  v_projects integer;
  v_sites integer;
  v_site_exists boolean;
begin
  if new.user_id <> (select auth.uid()) then
    raise exception 'Project owner mismatch' using errcode = '42501';
  end if;
  select case
    when p.role = 'ADMIN' or p.plan = 'PRO' then 'PRO'
    when p.plan = 'PLUS' or p.sostagora_access then 'PLUS'
    else 'FREE'
  end into v_plan
  from public.climaflora_profiles p where p.id = new.user_id;
  v_plan := coalesce(v_plan, 'FREE');
  v_project_limit := case v_plan when 'PRO' then 250 when 'PLUS' then 10 else 1 end;
  v_site_limit := case v_plan when 'PRO' then 50 when 'PLUS' then 5 else 1 end;

  select count(*) into v_projects from public.climaflora_projects p
  where p.user_id = new.user_id and (tg_op = 'INSERT' or p.id <> new.id);
  if v_projects >= v_project_limit then
    raise exception 'Project quota reached for plan %', v_plan using errcode = 'P0001';
  end if;

  if new.latitude is not null and new.longitude is not null then
    select exists (
      select 1 from public.climaflora_projects p
      where p.user_id = new.user_id
        and (tg_op = 'INSERT' or p.id <> new.id)
        and p.latitude = new.latitude and p.longitude = new.longitude
    ) into v_site_exists;
    if not v_site_exists then
      select count(*) into v_sites from (
        select distinct p.latitude, p.longitude
        from public.climaflora_projects p
        where p.user_id = new.user_id
          and (tg_op = 'INSERT' or p.id <> new.id)
          and p.latitude is not null and p.longitude is not null
      ) sites;
      if v_sites >= v_site_limit then
        raise exception 'Site quota reached for plan %', v_plan using errcode = 'P0001';
      end if;
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function public.climaflora_enforce_project_quota() from public, anon, authenticated;
drop trigger if exists climaflora_project_quota on public.climaflora_projects;
create trigger climaflora_project_quota
before insert or update on public.climaflora_projects
for each row execute function public.climaflora_enforce_project_quota();

create or replace function public.climaflora_enforce_comparison_quota()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_limit integer;
begin
  if new.user_id <> (select auth.uid()) then
    raise exception 'Comparison owner mismatch' using errcode = '42501';
  end if;
  select case
    when p.role = 'ADMIN' or p.plan = 'PRO' then 20
    when p.plan = 'PLUS' or p.sostagora_access then 5
    else 0
  end into v_limit
  from public.climaflora_profiles p where p.id = new.user_id;
  v_limit := coalesce(v_limit, 0);
  if cardinality(new.taxon_ids) > v_limit then
    raise exception 'Comparison quota reached (% plants)', v_limit using errcode = 'P0001';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function public.climaflora_enforce_comparison_quota() from public, anon, authenticated;
drop trigger if exists climaflora_comparison_quota on public.climaflora_comparisons;
create trigger climaflora_comparison_quota
before insert or update on public.climaflora_comparisons
for each row execute function public.climaflora_enforce_comparison_quota();

create unique index if not exists climaflora_palette_unassigned_taxon_uidx
on public.climaflora_palette_items(user_id, taxon_id)
where project_id is null;

create table if not exists public.climaflora_exports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  export_kind text not null check (export_kind in ('CSV','PRINT')),
  created_at timestamptz not null default now()
);
create index if not exists climaflora_exports_user_month_idx
on public.climaflora_exports(user_id, created_at desc);
alter table public.climaflora_exports enable row level security;
revoke all on public.climaflora_exports from public, anon, authenticated;
grant select, insert, delete on public.climaflora_exports to service_role;

create or replace function public.climaflora_record_export(p_kind text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user uuid := (select auth.uid());
  v_kind text := upper(trim(coalesce(p_kind, '')));
  v_limit integer;
  v_used integer;
begin
  if v_user is null then raise exception 'Authentication required' using errcode = '42501'; end if;
  if v_kind not in ('CSV','PRINT') then raise exception 'Invalid export kind'; end if;
  select case
    when p.role = 'ADMIN' or p.plan = 'PRO' then 100
    when p.plan = 'PLUS' or p.sostagora_access then 10
    else 0
  end into v_limit from public.climaflora_profiles p where p.id = v_user;
  v_limit := coalesce(v_limit, 0);
  select count(*) into v_used from public.climaflora_exports e
  where e.user_id = v_user and e.created_at >= date_trunc('month', now());
  if v_used >= v_limit then raise exception 'Monthly export quota reached' using errcode = 'P0001'; end if;
  insert into public.climaflora_exports(user_id, export_kind) values (v_user, v_kind);
  return jsonb_build_object('used', v_used + 1, 'limit', v_limit, 'remaining', v_limit - v_used - 1);
end;
$$;

revoke all on function public.climaflora_record_export(text) from public, anon;
grant execute on function public.climaflora_record_export(text) to authenticated, service_role;

commit;
