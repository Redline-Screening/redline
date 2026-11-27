-- Adds the daily limit and the number of checks used to the AI status. Run after 012. Safe to run again.
begin;
create or replace function public.ai_remaining(p_uid uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  b public.ai_budget;
  today date := (now() at time zone 'Europe/Zurich')::date;
  user_limit int;
  user_used int;
  global_used int;
  budget_left numeric;
begin
  select * into b from public.ai_budget where kind = 'manual';
  select coalesce((select a.daily_limit from public.accounts a where a.user_id = p_uid), b.daily_user) into user_limit;
  if exists (select 1 from public.accounts a where a.user_id = p_uid and a.read_only) then
    user_limit := 0;
  end if;
  select count(*) into user_used from public.ai_checks c where c.kind = 'manual' and c.user_id = p_uid and c.day = today;
  select count(*) into global_used from public.ai_checks c where c.kind = 'manual' and c.day = today;
  select b.total - coalesce(sum(coalesce(c.cost, b.reserve)), 0) into budget_left from public.ai_checks c
    where c.kind in ('manual', 'summary');
  return jsonb_build_object(
    'user', greatest(user_limit - user_used, 0), 'global', greatest(b.daily_global - global_used, 0),
    'budget', greatest(floor(budget_left / b.reserve), 0),
    'remaining', greatest(least(user_limit - user_used, b.daily_global - global_used, floor(budget_left / b.reserve)), 0),
    'user_limit', user_limit, 'used', user_used, 'global_limit', b.daily_global);
end $$;
commit;
