-- Portfolio Monitoring: selected companies, manual runs, limits. Run after 009. Safe to run again.
begin;

alter table public.holdings add column if not exists monitored boolean not null default false;
alter table public.scores add column if not exists monitor_checked date;       -- last monitoring check
alter table public.scores add column if not exists monitor_new boolean not null default false;
alter table public.workspaces add column if not exists monitor_manual_date date;
alter table public.workspaces add column if not exists monitor_last_kind text;

-- At most 10 monitored companies per user.
create or replace function public.limit_monitored() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.monitored and (select count(*) from public.holdings h
                        where h.user_id = new.user_id and h.monitored and h.id <> new.id) >= 10 then
    raise exception 'At most 10 companies can be monitored';
  end if;
  return new;
end $$;
drop trigger if exists limit_monitored on public.holdings;
create trigger limit_monitored before insert or update of monitored on public.holdings
  for each row execute function public.limit_monitored();

-- Monitoring: at most 10 checks per day across all users, $4 in total.
update public.ai_budget set daily_global = 10 where kind = 'monitor';

create or replace function public.monitor_status() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  b public.ai_budget;
  today date := (now() at time zone 'Europe/Zurich')::date;
  used int;
  spent numeric;
begin
  select * into b from public.ai_budget where kind = 'monitor';
  select count(*) into used from public.ai_checks where kind = 'monitor' and day = today;
  select coalesce(sum(coalesce(cost, b.reserve)), 0) into spent from public.ai_checks where kind = 'monitor';
  return jsonb_build_object(
    'global', greatest(b.daily_global - used, 0),
    'budget', greatest(floor((b.total - spent) / b.reserve), 0),
    'run_today', coalesce((select w.monitor_manual_date = today from public.workspaces w where w.user_id = auth.uid()), false),
    'read_only', exists (select 1 from public.accounts a where a.user_id = auth.uid() and a.read_only));
end $$;

-- "Run now": once per day per user.
create or replace function public.start_monitoring_run() returns boolean
language plpgsql security definer set search_path = '' as $$
declare
  today date := (now() at time zone 'Europe/Zurich')::date;
begin
  if auth.uid() is null or exists (select 1 from public.accounts a where a.user_id = auth.uid() and a.read_only) then
    return false;
  end if;
  update public.workspaces set monitor_manual_date = today
  where user_id = auth.uid() and monitor_manual_date is distinct from today;
  return found;
end $$;

create or replace function public.reserve_monitor_check(p_model text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  s jsonb;
  new_id uuid;
begin
  if uid is null or exists (select 1 from public.accounts a where a.user_id = uid and a.read_only) then
    return jsonb_build_object('reason', 'daily');
  end if;
  perform pg_advisory_xact_lock(hashtext('redline-ai-monitor'));
  s := public.monitor_status();
  if (s->>'global')::int < 1 then
    return jsonb_build_object('reason', 'daily');
  end if;
  if (s->>'budget')::int < 1 then
    return jsonb_build_object('reason', 'budget');
  end if;
  insert into public.ai_checks (user_id, kind, model) values (uid, 'monitor', left(p_model, 80)) returning id into new_id;
  return jsonb_build_object('id', new_id);
end $$;

revoke execute on function public.monitor_status() from public, anon;
revoke execute on function public.start_monitoring_run() from public, anon;
revoke execute on function public.reserve_monitor_check(text) from public, anon;
grant execute on function public.monitor_status() to authenticated;
grant execute on function public.start_monitoring_run() to authenticated;
grant execute on function public.reserve_monitor_check(text) to authenticated;
commit;
