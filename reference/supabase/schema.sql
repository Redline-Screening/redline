-- Redline database schema for Supabase (Postgres).
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Every table is protected by row-level security: each signed-in user can
-- only read and write their own rows.

create extension if not exists pgcrypto;

-- One workspace (fund settings) per user
create table if not exists public.workspaces (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  name       text,
  mode       text check (mode in ('provider', 'ai', 'both')),
  monitor    jsonb not null default '{"enabled": false, "issuers": "all", "criteria": []}'::jsonb,
  providers  jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Companies in the fund universe (holdings and prospects)
create table if not exists public.holdings (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name       text not null,
  ticker     text,
  isin       text,
  weight     numeric default 0,
  ytd        numeric,
  r1y        numeric,
  country    text,
  sector     text,
  type       text not null default 'holding' check (type in ('holding', 'prospect')),
  scores     jsonb not null default '{}'::jsonb,   -- { <criterion id>: { exposure, likelihood, controversy: {...}, ... } }
  updated_at timestamptz not null default now()
);
create index if not exists holdings_user_idx on public.holdings (user_id);

-- Exclusion / screening criteria
create table if not exists public.criteria (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  key               text,                       -- template key, e.g. 'military'
  label             text not null,
  description       text,
  threshold         numeric not null default 0, -- max % of revenue allowed
  watch_at          numeric not null default 50,-- likelihood (0-100) that puts a company on watch
  controversy_limit text not null default 'high' check (controversy_limit in ('medium', 'high', 'severe')),
  keywords          text[] not null default '{}',
  active            boolean not null default true,
  sort              int not null default 0,
  created_at        timestamptz not null default now()
);
create index if not exists criteria_user_idx on public.criteria (user_id);

-- Alerts (news, controversies, RepRisk incidents)
create table if not exists public.alerts (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  title      text not null,
  summary    text,
  date       date,
  severity   text not null default 'medium' check (severity in ('high', 'medium', 'low')),
  tickers    text[] not null default '{}',
  criteria   text[] not null default '{}',   -- criterion ids
  url        text,
  origin     text,                           -- web | ai | reprisk | manual
  source     text,
  status     text not null default 'new' check (status in ('new', 'reviewed', 'escalated', 'dismissed')),
  created_at timestamptz not null default now()
);
create index if not exists alerts_user_idx on public.alerts (user_id, date desc);

-- Row-level security: users only see and change their own rows
alter table public.workspaces enable row level security;
alter table public.holdings   enable row level security;
alter table public.criteria   enable row level security;
alter table public.alerts     enable row level security;

drop policy if exists "own workspace" on public.workspaces;
create policy "own workspace" on public.workspaces
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own holdings" on public.holdings;
create policy "own holdings" on public.holdings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own criteria" on public.criteria;
create policy "own criteria" on public.criteria
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own alerts" on public.alerts;
create policy "own alerts" on public.alerts
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
