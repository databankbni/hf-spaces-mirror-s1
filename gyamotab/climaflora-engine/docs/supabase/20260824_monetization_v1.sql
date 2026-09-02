-- Applied to the ClimaFlora Supabase project on 2026-08-24.
-- Idempotent runtime schema and access hardening for monetization v1.
begin;

create unique index if not exists climaflora_profiles_stripe_customer_uidx
  on public.climaflora_profiles (stripe_customer_id)
  where stripe_customer_id is not null;

create unique index if not exists climaflora_profiles_stripe_subscription_uidx
  on public.climaflora_profiles (stripe_subscription_id)
  where stripe_subscription_id is not null;

create index if not exists climaflora_palette_items_project_id_idx
  on public.climaflora_palette_items (project_id);

alter table public.climaflora_profiles
  drop constraint if exists climaflora_profiles_billing_status_check;
alter table public.climaflora_profiles
  add constraint climaflora_profiles_billing_status_check
  check (billing_status is null or billing_status in (
    'incomplete', 'incomplete_expired', 'trialing', 'active',
    'past_due', 'canceled', 'unpaid', 'paused'
  ));

alter table public.climaflora_profiles
  drop constraint if exists climaflora_profiles_billing_interval_check;
alter table public.climaflora_profiles
  add constraint climaflora_profiles_billing_interval_check
  check (billing_interval is null or billing_interval in ('monthly', 'yearly'));

create table if not exists public.climaflora_billing_events (
  stripe_event_id text primary key,
  event_type text not null,
  stripe_created bigint,
  received_at timestamptz not null default now(),
  processed boolean not null default false,
  processing_error text
);

alter table public.climaflora_billing_events enable row level security;
revoke all on table public.climaflora_billing_events from public, anon, authenticated;
grant select, insert, update, delete on table public.climaflora_billing_events to service_role;

revoke insert, update, delete on table public.climaflora_profiles from anon, authenticated;

revoke execute on function public.climaflora_admin_set_plan(uuid, text) from public, anon;
revoke execute on function public.climaflora_admin_users() from public, anon;
revoke execute on function public.climaflora_create_profile() from public, anon, authenticated;
revoke execute on function public.climaflora_delete_own_account() from public, anon;
revoke execute on function public.climaflora_has_plus() from public, anon;
revoke execute on function public.climaflora_is_admin() from public, anon;
revoke execute on function public.climaflora_update_own_profile(text, text) from public, anon;
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

grant execute on function public.climaflora_admin_set_plan(uuid, text) to authenticated, service_role;
grant execute on function public.climaflora_admin_users() to authenticated, service_role;
grant execute on function public.climaflora_delete_own_account() to authenticated, service_role;
grant execute on function public.climaflora_has_plus() to authenticated, service_role;
grant execute on function public.climaflora_is_admin() to authenticated, service_role;
grant execute on function public.climaflora_update_own_profile(text, text) to authenticated, service_role;

drop policy if exists "climaflora profile self read" on public.climaflora_profiles;
create policy "climaflora profile self read"
on public.climaflora_profiles
for select
to authenticated
using (id = (select auth.uid()));

commit;
