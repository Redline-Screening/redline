-- Status summaries per company and criterion, and their cost log. Run after 008. Safe to run again.
begin;

alter table public.scores add column if not exists summary text;
alter table public.scores add column if not exists summary_date date;
alter table public.scores add column if not exists summary_key text;   -- the status and findings it describes

alter table public.ai_checks drop constraint if exists ai_checks_kind_check;
alter table public.ai_checks add constraint ai_checks_kind_check check (kind in ('manual', 'monitor', 'summary'));

-- Summaries count towards the manual budget, not towards the daily number of checks.
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
    where c.kind in ('manual', 'summary');
  return jsonb_build_object(
    'user', greatest(user_left, 0), 'global', greatest(global_left, 0),
    'budget', greatest(floor(budget_left / b.reserve), 0),
    'remaining', greatest(least(user_left, global_left, floor(budget_left / b.reserve)), 0));
end $$;

-- Records one summary. Refused for read-only accounts and when the budget is used.
create or replace function public.log_ai_summary(p_model text, p_input int, p_output int, p_cost numeric)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null or exists (select 1 from public.accounts a where a.user_id = uid and a.read_only)
     or (public.ai_remaining(uid)->>'budget')::int < 1 then
    return false;
  end if;
  insert into public.ai_checks (user_id, kind, model, status, searches, input_tokens, output_tokens, cost)
  values (uid, 'summary', left(p_model, 80), 'done', 0, greatest(p_input, 0), greatest(p_output, 0), greatest(coalesce(p_cost, 0), 0));
  return true;
end $$;

-- Whether a summary may be generated now (budget left, not read-only).
create or replace function public.can_summarize() returns boolean
language sql security definer set search_path = '' as $$
  select auth.uid() is not null
     and not exists (select 1 from public.accounts a where a.user_id = auth.uid() and a.read_only)
     and (public.ai_remaining(auth.uid())->>'budget')::int >= 1;
$$;

revoke execute on function public.log_ai_summary(text, int, int, numeric) from public, anon;
revoke execute on function public.can_summarize() from public, anon;
grant execute on function public.log_ai_summary(text, int, int, numeric) to authenticated;
grant execute on function public.can_summarize() to authenticated;
commit;
