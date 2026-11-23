-- Redline database schema (Supabase).
-- Supabase: SQL Editor -> New query -> paste -> Run. Safe to run again.
-- Row-level security: each signed-in user can only reach their own rows.

create table if not exists public.workspaces (
  user_id          uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  name             text,
  mode             text check (mode in ('provider', 'ai', 'both')),
  monitor          jsonb not null default '{"enabled": false, "issuers": "all", "criteria": []}'::jsonb,
  monitor_last_run date,          -- written by the daily job only, separate from the settings above
  monitor_note     text,
  providers        jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now()
);

create table if not exists public.holdings (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name       text not null check (name <> ''),
  ticker     text,
  isin       text check (isin <> ''),            -- null when unknown
  weight     numeric not null default 0,
  ytd        numeric,
  r1y        numeric,
  country    text,
  sector     text,
  type       text not null default 'holding' check (type in ('holding', 'prospect')),
  updated_at timestamptz not null default now(),
  unique (user_id, isin),
  unique (id, user_id)
);

create table if not exists public.criteria (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  key               text,
  label             text not null check (label <> ''),
  description       text,
  threshold         numeric not null default 0 check (threshold between 0 and 100),
  watch_at          numeric not null default 50 check (watch_at between 0 and 100),
  controversy_limit text not null default 'high' check (controversy_limit in ('medium', 'high', 'severe')),
  keywords          text[] not null default '{}',
  active            boolean not null default true,
  sort              int not null default 0,
  created_at        timestamptz not null default now(),
  unique (user_id, key),
  unique (id, user_id)
);

-- One row per company and criterion. The composite foreign keys guarantee
-- that the company and the criterion belong to the same user as the score.
create table if not exists public.scores (
  holding_id    uuid not null,
  criterion_id  uuid not null,
  user_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  exposure      numeric check (exposure between 0 and 100),
  exposure_kind text check (exposure_kind in ('provider', 'analyst', 'ai_web', 'ai_estimate')),
  source        text,             -- display name, e.g. 'MSCI ESG Research'
  basis         text,
  exposure_date date,
  likelihood    numeric check (likelihood between 0 and 100),
  confidence    text check (confidence in ('low', 'medium', 'high')),
  rationale     text,
  signals       text[] not null default '{}',
  controversy   jsonb,
  updated_at    timestamptz not null default now(),
  primary key (holding_id, criterion_id),
  foreign key (holding_id, user_id) references public.holdings (id, user_id) on delete cascade,
  foreign key (criterion_id, user_id) references public.criteria (id, user_id) on delete cascade,
  check (exposure is null or exposure_kind is not null)
);
create index if not exists scores_user_idx on public.scores (user_id);
create index if not exists scores_criterion_idx on public.scores (criterion_id);

create table if not exists public.alerts (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  title      text not null,
  summary    text,
  date       date,
  severity   text not null default 'medium' check (severity in ('high', 'medium', 'low')),
  tickers    text[] not null default '{}',
  criteria   text[] not null default '{}',
  url        text,
  origin     text,
  source     text,
  status     text not null default 'new' check (status in ('new', 'reviewed', 'escalated', 'dismissed')),
  created_at timestamptz not null default now()
);
create index if not exists alerts_user_idx on public.alerts (user_id, date desc);

create table if not exists public.ai_usage (
  user_id uuid not null references auth.users (id) on delete cascade,
  day     date not null default current_date,
  checks  int not null default 0,
  primary key (user_id, day)
);

-- AI estimates never replace a provider or analyst figure.
create or replace function public.protect_exposure() returns trigger
language plpgsql set search_path = '' as $$
begin
  if old.exposure is not null
     and old.exposure_kind in ('provider', 'analyst')
     and (new.exposure is null or new.exposure_kind in ('ai_web', 'ai_estimate')) then
    raise exception 'Provider and analyst figures cannot be replaced by AI estimates';
  end if;
  return new;
end $$;

drop trigger if exists protect_exposure on public.scores;
create trigger protect_exposure before update on public.scores
  for each row execute function public.protect_exposure();

-- Counts one AI check for the signed-in user. Returns false at the daily limit (40).
create or replace function public.use_ai_check() returns boolean
language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    return false;
  end if;
  insert into public.ai_usage as u (user_id, day, checks) values (uid, current_date, 1)
  on conflict (user_id, day) do update set checks = u.checks + 1 where u.checks < 40;
  return found;
end $$;

revoke execute on function public.use_ai_check() from public, anon;
grant execute on function public.use_ai_check() to authenticated;

-- Row-level security
alter table public.workspaces enable row level security;
alter table public.holdings   enable row level security;
alter table public.criteria   enable row level security;
alter table public.scores     enable row level security;
alter table public.alerts     enable row level security;
alter table public.ai_usage   enable row level security;

drop policy if exists "own workspace" on public.workspaces;
create policy "own workspace" on public.workspaces for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists "own holdings" on public.holdings;
create policy "own holdings" on public.holdings for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists "own criteria" on public.criteria;
create policy "own criteria" on public.criteria for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists "own scores" on public.scores;
create policy "own scores" on public.scores for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists "own alerts" on public.alerts;
create policy "own alerts" on public.alerts for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists "own usage" on public.ai_usage;
create policy "own usage" on public.ai_usage for select to authenticated
  using (user_id = (select auth.uid()));

-- Access rights
revoke all on public.workspaces, public.holdings, public.criteria, public.scores, public.alerts, public.ai_usage from anon, authenticated;
grant select, insert, update, delete on public.workspaces, public.holdings, public.criteria, public.scores, public.alerts to authenticated;
grant select on public.ai_usage to authenticated;
grant all on public.workspaces, public.holdings, public.criteria, public.scores, public.alerts, public.ai_usage to service_role;
