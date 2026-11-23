-- Findings, AI limits and cost log. Run after schema.sql and 002.
-- Supabase: SQL Editor -> New query -> paste -> Run. Safe to run again.
begin;

-- Findings: links between a company and a criterion, always with sources
create table if not exists public.findings (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  holding_id   uuid not null,
  criterion_id uuid not null,
  category     text not null default 'other' check (category in
    ('scandal', 'court', 'ngo', 'supply_chain', 'contract', 'investment', 'subsidiary', 'financing', 'other')),
  title        text not null,
  summary      text not null,
  date         date,                      -- null: date unknown
  severity     text not null check (severity in ('low', 'medium', 'high', 'severe')),
  sources      jsonb not null check (jsonb_typeof(sources) = 'array' and jsonb_array_length(sources) > 0),
  status       text not null default 'open' check (status in ('open', 'dismissed')),
  first_seen   date not null default current_date,
  last_seen    date not null default current_date,
  unique (id, user_id),
  foreign key (holding_id, user_id) references public.holdings (id, user_id) on delete cascade,
  foreign key (criterion_id, user_id) references public.criteria (id, user_id) on delete cascade
);
create index if not exists findings_pair_idx on public.findings (holding_id, criterion_id);
create index if not exists findings_user_idx on public.findings (user_id);
create index if not exists findings_criterion_idx on public.findings (criterion_id);

alter table public.alerts add column if not exists finding_id uuid;
alter table public.alerts drop constraint if exists alerts_finding_unique;
alter table public.alerts add constraint alerts_finding_unique unique (finding_id);
alter table public.alerts drop constraint if exists alerts_finding_fk;
alter table public.alerts add constraint alerts_finding_fk
  foreign key (finding_id, user_id) references public.findings (id, user_id) on delete cascade;
alter table public.alerts drop constraint if exists alerts_severity_check;
alter table public.alerts add constraint alerts_severity_check check (severity in ('severe', 'high', 'medium', 'low'));

-- Account settings, changed only by the project owner in the Supabase dashboard
create table if not exists public.accounts (
  user_id     uuid primary key references auth.users (id) on delete cascade,
  daily_limit int check (daily_limit >= 0),        -- null: standard limit
  read_only   boolean not null default false
);

-- Limits and budgets in US dollars, changed only in the Supabase dashboard
create table if not exists public.ai_budget (
  kind         text primary key check (kind in ('manual', 'monitor')),
  total        numeric not null,
  daily_global int not null,
  daily_user   int,
  reserve      numeric not null                    -- counted for a check until its cost is known
);
insert into public.ai_budget (kind, total, daily_global, daily_user, reserve) values
  ('manual', 12, 60, 15, 0.50), ('monitor', 4, 5, null, 0.10)
on conflict (kind) do nothing;

create table if not exists public.ai_checks (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users (id) on delete set null,   -- the cost stays recorded
  kind          text not null check (kind in ('manual', 'monitor')),
  model         text not null,
  day           date not null default ((now() at time zone 'Europe/Zurich')::date),
  status        text not null default 'reserved' check (status in ('reserved', 'done', 'failed')),
  searches      int,
  input_tokens  int,
  output_tokens int,
  cost          numeric check (cost >= 0),
  created_at    timestamptz not null default now()
);
create index if not exists ai_checks_day_idx on public.ai_checks (kind, day);
create index if not exists ai_checks_user_idx on public.ai_checks (user_id, day);

drop function if exists public.use_ai_check();
drop table if exists public.ai_usage;

-- Remaining checks for one user: the smallest of the daily and budget limits
create or replace function public.ai_remaining(p_uid uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  b public.ai_budget;
  today date := (now() at time zone 'Europe/Zurich')::date;
  user_limit int;
  user_left int;
  global_left int;
  budget_left numeric;
begin
  select * into b from public.ai_budget where kind = 'manual';
  select coalesce((select a.daily_limit from public.accounts a where a.user_id = p_uid), b.daily_user) into user_limit;
  if exists (select 1 from public.accounts a where a.user_id = p_uid and a.read_only) then
    user_limit := 0;
  end if;
  select user_limit - count(*) into user_left from public.ai_checks c
    where c.kind = 'manual' and c.user_id = p_uid and c.day = today;
  select b.daily_global - count(*) into global_left from public.ai_checks c
    where c.kind = 'manual' and c.day = today;
  select b.total - coalesce(sum(coalesce(c.cost, b.reserve)), 0) into budget_left from public.ai_checks c
    where c.kind = 'manual';
  return jsonb_build_object(
    'user', greatest(user_left, 0), 'global', greatest(global_left, 0),
    'budget', greatest(floor(budget_left / b.reserve), 0),
    'remaining', greatest(least(user_left, global_left, floor(budget_left / b.reserve)), 0));
end $$;

create or replace function public.ai_status() returns jsonb
language sql security definer set search_path = '' as $$
  select public.ai_remaining(auth.uid());
$$;

-- Counts one check before the AI is called. Returns {id} or {reason: 'daily' | 'budget'}.
create or replace function public.reserve_ai_check(p_model text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  r jsonb;
  new_id uuid;
begin
  if uid is null then
    return jsonb_build_object('reason', 'daily');
  end if;
  perform pg_advisory_xact_lock(hashtext('redline-ai-manual'));
  r := public.ai_remaining(uid);
  if (r->>'user')::int < 1 or (r->>'global')::int < 1 then
    return jsonb_build_object('reason', 'daily');
  end if;
  if (r->>'budget')::int < 1 then
    return jsonb_build_object('reason', 'budget');
  end if;
  insert into public.ai_checks (user_id, kind, model) values (uid, 'manual', left(p_model, 80)) returning id into new_id;
  return jsonb_build_object('id', new_id);
end $$;

-- Records the actual cost once
create or replace function public.finish_ai_check(p_id uuid, p_status text, p_searches int, p_input int, p_output int, p_cost numeric)
returns void language sql security definer set search_path = '' as $$
  update public.ai_checks set status = p_status, searches = p_searches, input_tokens = p_input,
    output_tokens = p_output, cost = p_cost
  where id = p_id and user_id = auth.uid() and status = 'reserved' and p_status in ('done', 'failed');
$$;

revoke execute on function public.ai_remaining(uuid) from public, anon, authenticated;
revoke execute on function public.ai_status() from public, anon;
revoke execute on function public.reserve_ai_check(text) from public, anon;
revoke execute on function public.finish_ai_check(uuid, text, int, int, int, numeric) from public, anon;
grant execute on function public.ai_status() to authenticated;
grant execute on function public.reserve_ai_check(text) to authenticated;
grant execute on function public.finish_ai_check(uuid, text, int, int, int, numeric) to authenticated;

alter table public.findings  enable row level security;
alter table public.accounts  enable row level security;
alter table public.ai_budget enable row level security;
alter table public.ai_checks enable row level security;

drop policy if exists "own findings" on public.findings;
create policy "own findings" on public.findings for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists "own account" on public.accounts;
create policy "own account" on public.accounts for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists "own checks" on public.ai_checks;
create policy "own checks" on public.ai_checks for select to authenticated using (user_id = (select auth.uid()));

revoke all on public.findings, public.accounts, public.ai_budget, public.ai_checks from anon, authenticated;
grant select, insert, update, delete on public.findings to authenticated;
grant select on public.accounts, public.ai_checks to authenticated;
grant all on public.findings, public.accounts, public.ai_budget, public.ai_checks to service_role;

commit;
