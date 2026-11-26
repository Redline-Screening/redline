-- Copies screening results into the demo account and makes it read-only.
-- Supabase: SQL Editor -> New query -> paste -> replace the two addresses -> Run.
-- Can be run again: it replaces the demo data. Do not save addresses in this file.
-- Copied: companies with findings or scores, active criteria, scores, findings, alerts.
do $$
declare
  source_email text := 'SOURCE_ADDRESS';
  demo_email   text := 'DEMO_ADDRESS';
  src uuid;
  demo uuid;
begin
  select id into src from auth.users where lower(email) = lower(source_email);
  select id into demo from auth.users where lower(email) = lower(demo_email);
  if src is null or demo is null then
    raise exception 'Account not found. Check both addresses.';
  end if;
  if src = demo then
    raise exception 'The two addresses must be different.';
  end if;
  -- Protects a normal account from being overwritten by mistake.
  if not exists (select 1 from public.accounts where user_id = demo and read_only)
     and exists (select 1 from public.holdings where user_id = demo) then
    raise exception 'The demo account already has data and is not marked read-only. Nothing was changed.';
  end if;
  if exists (select 1 from public.scores where user_id = src and exposure_kind = 'provider') then
    raise exception 'The source account contains provider figures. Remove them first. Nothing was changed.';
  end if;

  create temp table map_h on commit drop as
    select h.id as old_id, gen_random_uuid() as new_id from public.holdings h
    where h.user_id = src and (exists (select 1 from public.scores s where s.holding_id = h.id)
                            or exists (select 1 from public.findings f where f.holding_id = h.id));
  create temp table map_c on commit drop as
    select id as old_id, gen_random_uuid() as new_id from public.criteria where user_id = src and active;
  create temp table map_f on commit drop as
    select f.id as old_id, gen_random_uuid() as new_id from public.findings f
    where f.user_id = src and f.holding_id in (select old_id from map_h) and f.criterion_id in (select old_id from map_c);

  delete from public.alerts where user_id = demo;
  delete from public.holdings where user_id = demo;
  delete from public.criteria where user_id = demo;
  delete from public.workspaces where user_id = demo;

  insert into public.workspaces (user_id, name, mode)
    select demo, coalesce(name, 'Demo Fund'), coalesce(mode, 'ai') from public.workspaces where user_id = src;

  insert into public.holdings
    select (jsonb_populate_record(null::public.holdings, to_jsonb(h) || jsonb_build_object('id', m.new_id, 'user_id', demo))).*
    from public.holdings h join map_h m on m.old_id = h.id;

  insert into public.criteria
    select (jsonb_populate_record(null::public.criteria, to_jsonb(c) || jsonb_build_object('id', m.new_id, 'user_id', demo))).*
    from public.criteria c join map_c m on m.old_id = c.id;

  insert into public.scores
    select (jsonb_populate_record(null::public.scores, to_jsonb(s) ||
      jsonb_build_object('holding_id', h.new_id, 'criterion_id', c.new_id, 'user_id', demo))).*
    from public.scores s join map_h h on h.old_id = s.holding_id join map_c c on c.old_id = s.criterion_id;

  insert into public.findings
    select (jsonb_populate_record(null::public.findings, to_jsonb(f) ||
      jsonb_build_object('id', m.new_id, 'holding_id', h.new_id, 'criterion_id', c.new_id, 'user_id', demo))).*
    from public.findings f join map_f m on m.old_id = f.id
    join map_h h on h.old_id = f.holding_id join map_c c on c.old_id = f.criterion_id;

  insert into public.alerts
    select (jsonb_populate_record(null::public.alerts, to_jsonb(a) || jsonb_build_object(
      'id', gen_random_uuid(), 'user_id', demo, 'finding_id', m.new_id,
      'criteria', (select coalesce(jsonb_agg(c.new_id), '[]'::jsonb) from map_c c where c.old_id::text = any (a.criteria))))).*
    from public.alerts a join map_f m on m.old_id = a.finding_id;

  -- Alert log (migration 011): entries of the copied companies, with their dates.
  if to_regclass('public.alert_log') is not null then
    delete from public.alert_log where user_id = demo;
    insert into public.alert_log (user_id, day, origin, holding_id, criterion_id, issuer, isin, criterion, status, change,
                                  severity, summary, sources)
      select demo, l.day, l.origin, h.new_id, c.new_id, l.issuer, l.isin, l.criterion, l.status, l.change, l.severity,
             l.summary, l.sources
      from public.alert_log l join map_h h on h.old_id = l.holding_id left join map_c c on c.old_id = l.criterion_id
      where l.user_id = src and (l.criterion_id is null or c.new_id is not null);
  end if;

  insert into public.accounts (user_id, daily_limit, read_only) values (demo, 0, true)
  on conflict (user_id) do update set daily_limit = 0, read_only = true;
end $$;

select 'Demo account: ' || (select count(*) from public.holdings h where h.user_id = a.user_id) || ' companies, '
  || (select count(*) from public.findings f where f.user_id = a.user_id) || ' findings, '
  || (select count(*) from public.alerts x where x.user_id = a.user_id) || ' alerts' as result
from public.accounts a where a.read_only;
