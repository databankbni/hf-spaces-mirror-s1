-- ═══════════════════════════════════════════════════════════════
-- KOMBAZ CREDITS — Closed-Loop Stored Value Wallet
-- Run this in Supabase SQL Editor (Project → SQL Editor → New query)
-- ═══════════════════════════════════════════════════════════════
-- DESIGN PRINCIPLE: the wallet has NO mutable "balance" column.
-- Balance = SUM of all ledger rows for a user. This is an append-only
-- ledger (like accounting), so nothing can silently corrupt or be
-- edited after the fact — every credit/debit is a permanent, timestamped
-- row. This also happens to be exactly what a regulator would want to
-- see if they ever asked "prove this is closed-loop and never cashed out".

create extension if not exists "uuid-ossp";

-- One row per kombaz user (mirrors your Supabase Auth users table)
create table if not exists wallet_accounts (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  display_name  text,
  created_at    timestamptz not null default now(),
  frozen        boolean not null default false  -- kill-switch: freeze a single account
);

-- The ledger. Every top-up, spend, refund, or admin adjustment is a row.
-- amount_cents is SIGNED: positive = credit added, negative = credit spent.
create table if not exists wallet_ledger (
  id            bigint generated always as identity primary key,
  user_id       uuid not null references wallet_accounts(user_id) on delete cascade,
  amount_cents  bigint not null,                 -- signed, in agorot (₪0.01)
  kind          text not null,                   -- 'topup' | 'spend' | 'refund' | 'admin_adjust'
  source        text not null,                   -- 'gumroad' | 'paypal' | 'manual' | 'academy' | 'synth-store' | 'market-stall'
  reference_id  text,                             -- external order id (Gumroad sale_id etc.) — for idempotency
  description   text,
  created_at    timestamptz not null default now(),
  constraint amount_nonzero check (amount_cents <> 0)
);

-- Prevent the exact same external payment from being credited twice
-- (Gumroad/webhook retries are common — this makes top-ups idempotent)
create unique index if not exists wallet_ledger_reference_unique
  on wallet_ledger (source, reference_id)
  where reference_id is not null;

create index if not exists wallet_ledger_user_idx on wallet_ledger(user_id, created_at desc);

-- Convenience view: current balance per user, computed live from the ledger
create or replace view wallet_balances as
select
  user_id,
  coalesce(sum(amount_cents), 0) as balance_cents,
  coalesce(sum(amount_cents), 0)::numeric / 100.0 as balance_ils
from wallet_ledger
group by user_id;

-- Row Level Security — users can only ever read their own ledger/balance.
-- All writes happen through the backend service role (server-side only),
-- never directly from the browser with the user's own key. This matters:
-- if a user could INSERT their own ledger rows from the client, they
-- could mint themselves free credit.
alter table wallet_accounts enable row level security;
alter table wallet_ledger enable row level security;

create policy "users read own account" on wallet_accounts
  for select using (auth.uid() = user_id);

create policy "users read own ledger" on wallet_ledger
  for select using (auth.uid() = user_id);

-- No insert/update/delete policies for the anon/authenticated role at all.
-- Only the service_role key (used exclusively by your FastAPI backend,
-- never shipped to the browser) can write to wallet_ledger.
