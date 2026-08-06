-- ============================================================
-- KOMBAZ SYNTH — Supabase setup
-- Run this ONCE in the Supabase Dashboard → SQL Editor → New query
-- ============================================================

-- 1) profiles table — one row per signed-up user, linked to Supabase's
--    own auth.users table (which Supabase Auth manages automatically;
--    you never insert into auth.users yourself).
create table public.profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  email text,
  is_pro boolean not null default false,
  stripe_customer_id text,
  updated_at timestamptz not null default now()
);

-- 2) Row Level Security — locked down by default. Without this, ANY
--    authenticated client could read (or worse, write) any row.
alter table public.profiles enable row level security;

-- Users may read ONLY their own profile row.
create policy "Users can view their own profile"
  on public.profiles for select
  using (auth.uid() = id);

-- Deliberately NO insert/update/delete policy for regular users here.
-- The trigger below creates their row automatically (as the database
-- owner, bypassing RLS), and only the backend's Secret key (which
-- bypasses RLS entirely) is ever allowed to flip is_pro to true after a
-- real Stripe payment. A user should never be able to grant themselves
-- Pro by calling the Supabase client directly.

-- 3) Auto-create a profile the moment someone signs up, and
--    auto-grant permanent Pro if the email matches the admin's.
--    security definer = runs with the function owner's privileges, not
--    the signing-up user's — required since a brand new user has no
--    permission to insert into public.profiles on their own.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, is_pro)
  values (
    new.id,
    new.email,
    lower(new.email) = lower('shaikombaz@gmail.com')
  );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- 4) projects table — cloud save/load of the full track: every drum
--    channel, melodic channel, pattern, FX setting, preset choice —
--    everything collectTrack() already gathers for local save/load,
--    now also stored per-user in Supabase instead of (or alongside)
--    the browser's own localStorage.
-- ============================================================
create table public.projects (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users(id) on delete cascade not null,
  name text not null,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

-- one row per (user, name) — saving under an existing name overwrites
-- it (upsert), matching how the local "SAVE TRACK" already behaves
create unique index projects_user_name_idx on public.projects(user_id, name);

alter table public.projects enable row level security;

-- Unlike profiles (where only the backend may ever write), a project
-- is the user's own creative work — they save and load it directly
-- with their own session, so they get full CRUD on rows that are
-- theirs. RLS is what keeps this safe: auth.uid() = user_id means a
-- user can never see or touch anyone else's saved projects.
create policy "Users can view their own projects"
  on public.projects for select
  using (auth.uid() = user_id);

create policy "Users can insert their own projects"
  on public.projects for insert
  with check (auth.uid() = user_id);

create policy "Users can update their own projects"
  on public.projects for update
  using (auth.uid() = user_id);

create policy "Users can delete their own projects"
  on public.projects for delete
  using (auth.uid() = user_id);
