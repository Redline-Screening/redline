-- Dated alert log: one row per company and criterion per monitoring day, never changed afterwards.
-- Run after 010. Safe to run again.
begin;

create table if not exists public.alert_log (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  day               date not null,
  origin            text not null check (origin in ('monitoring', 'provider')),
  holding_id        uuid,                 -- kept as a reference only: the log stays if a company is removed
  criterion_id      uuid,
  issuer            text not null,
  isin              text,
  criterion         text,
  status            text not null check (status in ('breach', 'watch', 'provider')),
  change            text,
  severity          text,
  summary           text,
  sources           jsonb not null default '[]'::jsonb,
  provider_alert_id uuid,
  created_at        timestamptz not null default now(),
  unique (user_id, provider_alert_id)
);
create index if not exists alert_log_user_day_idx on public.alert_log (user_id, day desc);

alter table public.alert_log enable row level security;
drop policy if exists "own log" on public.alert_log;
create policy "own log" on public.alert_log for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists "no insert when read-only" on public.alert_log;
drop policy if exists "no delete when read-only" on public.alert_log;
create policy "no insert when read-only" on public.alert_log as restrictive for insert to authenticated
  with check (not (select public.is_read_only()));
create policy "no delete when read-only" on public.alert_log as restrictive for delete to authenticated
  using (not (select public.is_read_only()));

-- Entries are never edited: only insert, read, and the replacement of the same day's entry.
revoke all on public.alert_log from anon, authenticated;
grant select, insert, delete on public.alert_log to authenticated;
grant all on public.alert_log to service_role;
commit;
