-- Applied to the ClimaFlora Supabase project on 2026-08-24.
-- Sostagora grants remain independent from Stripe subscriptions.
begin;

alter table public.climaflora_profiles
  add column if not exists sostagora_access boolean not null default false,
  add column if not exists sostagora_wp_user_id bigint,
  add column if not exists sostagora_access_updated_at timestamptz;

create unique index if not exists climaflora_profiles_sostagora_wp_user_uidx
  on public.climaflora_profiles (sostagora_wp_user_id)
  where sostagora_wp_user_id is not null;

create table if not exists public.climaflora_sostagora_grants (
  wordpress_user_id bigint primary key,
  email_hash text not null,
  supabase_user_id uuid references auth.users(id) on delete set null,
  access_level text not null default 'none'
    check (access_level in ('none', 'sostagora', 'sostagora_elite')),
  active boolean not null default false,
  issued_at timestamptz,
  last_synced_at timestamptz not null default now(),
  linked_at timestamptz
);

create unique index if not exists climaflora_sostagora_grants_user_uidx
  on public.climaflora_sostagora_grants (supabase_user_id)
  where supabase_user_id is not null;

alter table public.climaflora_sostagora_grants enable row level security;
revoke all on table public.climaflora_sostagora_grants from public, anon, authenticated;
grant select, insert, update, delete on table public.climaflora_sostagora_grants to service_role;

create or replace function public.climaflora_has_plus()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.climaflora_profiles p
    where p.id = auth.uid()
      and (
        p.sostagora_access
        or (
          p.plan in ('PLUS', 'PRO')
          and p.billing_status in ('active', 'trialing')
        )
      )
  );
$$;

revoke execute on function public.climaflora_has_plus() from public, anon;
grant execute on function public.climaflora_has_plus() to authenticated, service_role;

commit;
