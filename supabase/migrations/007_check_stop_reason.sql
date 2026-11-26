-- Records why a check ended. Run after 006. Safe to run again.
begin;
alter table public.ai_checks add column if not exists stop_reason text;
alter table public.ai_checks add column if not exists rounds int;

drop function if exists public.finish_ai_check(uuid, text, int, int, int, numeric);
create or replace function public.finish_ai_check(p_id uuid, p_status text, p_searches int, p_input int, p_output int,
                                                  p_cost numeric, p_stop text default null, p_rounds int default null)
returns void language sql security definer set search_path = '' as $$
  update public.ai_checks set status = p_status, searches = p_searches, input_tokens = p_input,
    output_tokens = p_output, cost = p_cost, stop_reason = left(p_stop, 40), rounds = p_rounds
  where id = p_id and user_id = auth.uid() and status = 'reserved' and p_status in ('done', 'failed');
$$;
revoke execute on function public.finish_ai_check(uuid, text, int, int, int, numeric, text, int) from public, anon;
grant execute on function public.finish_ai_check(uuid, text, int, int, int, numeric, text, int) to authenticated;
commit;
