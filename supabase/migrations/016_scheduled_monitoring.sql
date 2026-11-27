-- Functions for the daily monitoring job (GitHub Actions). Only the secret key (service_role) may call them.
-- They apply the same limits and budgets as "Run now". Run after 015. Safe to run again.
begin;

create or replace function public.reserve_monitor_check_for(p_uid uuid, p_model text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  b public.ai_budget;
  today date := (now() at time zone 'Europe/Zurich')::date;
  used int;
  spent numeric;
  new_id uuid;
begin
  if exists (select 1 from public.accounts a where a.user_id = p_uid and a.read_only) then
    return jsonb_build_object('reason', 'daily');
  end if;
  perform pg_advisory_xact_lock(hashtext('redline-ai-monitor'));
  select * into b from public.ai_budget where kind = 'monitor';
  select count(*) into used from public.ai_checks where kind = 'monitor' and day = today;
  select coalesce(sum(coalesce(cost, b.reserve)), 0) into spent from public.ai_checks where kind = 'monitor';
  if used >= b.daily_global then
    return jsonb_build_object('reason', 'daily');
  end if;
  if b.total - spent < b.reserve then
    return jsonb_build_object('reason', 'budget');
  end if;
  insert into public.ai_checks (user_id, kind, model) values (p_uid, 'monitor', left(p_model, 80)) returning id into new_id;
  return jsonb_build_object('id', new_id);
end $$;

create or replace function public.finish_ai_check_for(p_uid uuid, p_id uuid, p_status text, p_searches int, p_input int,
                                                      p_output int, p_cost numeric, p_stop text default null,
                                                      p_rounds int default null)
returns void language sql security definer set search_path = '' as $$
  update public.ai_checks set status = p_status, searches = p_searches, input_tokens = p_input,
    output_tokens = p_output, cost = p_cost, stop_reason = left(p_stop, 40), rounds = p_rounds
  where id = p_id and user_id = p_uid and status = 'reserved' and p_status in ('done', 'failed');
$$;

create or replace function public.can_summarize_for(p_uid uuid) returns boolean
language sql security definer set search_path = '' as $$
  select not exists (select 1 from public.accounts a where a.user_id = p_uid and a.read_only)
     and (public.ai_remaining(p_uid)->>'budget')::int >= 1;
$$;

create or replace function public.log_ai_summary_for(p_uid uuid, p_model text, p_input int, p_output int, p_cost numeric)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_summarize_for(p_uid) then
    return false;
  end if;
  insert into public.ai_checks (user_id, kind, model, status, searches, input_tokens, output_tokens, cost)
  values (p_uid, 'summary', left(p_model, 80), 'done', 0, greatest(p_input, 0), greatest(p_output, 0), greatest(coalesce(p_cost, 0), 0));
  return true;
end $$;

revoke execute on function public.reserve_monitor_check_for(uuid, text) from public, anon, authenticated;
revoke execute on function public.finish_ai_check_for(uuid, uuid, text, int, int, int, numeric, text, int) from public, anon, authenticated;
revoke execute on function public.can_summarize_for(uuid) from public, anon, authenticated;
revoke execute on function public.log_ai_summary_for(uuid, text, int, int, numeric) from public, anon, authenticated;
grant execute on function public.reserve_monitor_check_for(uuid, text) to service_role;
grant execute on function public.finish_ai_check_for(uuid, uuid, text, int, int, int, numeric, text, int) to service_role;
grant execute on function public.can_summarize_for(uuid) to service_role;
grant execute on function public.log_ai_summary_for(uuid, text, int, int, numeric) to service_role;
commit;
