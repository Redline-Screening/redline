-- Pre-investment history: decision per company and dated investment notes. Run after 013. Safe to run again.
begin;
alter table public.holdings add column if not exists pre_investment boolean not null default false;  -- screened as pre-investment
alter table public.holdings add column if not exists decision text;
alter table public.holdings drop constraint if exists holdings_decision_check;
alter table public.holdings add constraint holdings_decision_check check (decision in ('review', 'prospect', 'rejected'));
update public.holdings set pre_investment = true, decision = coalesce(decision, 'review') where type = 'candidate';

create table if not exists public.company_notes (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  holding_id uuid not null,
  text       text not null check (char_length(text) between 1 and 1000),
  created_at timestamptz not null default now(),
  foreign key (holding_id, user_id) references public.holdings (id, user_id) on delete cascade
);
create index if not exists company_notes_holding_idx on public.company_notes (holding_id, created_at desc);

alter table public.company_notes enable row level security;
drop policy if exists "own notes" on public.company_notes;
create policy "own notes" on public.company_notes for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists "no insert when read-only" on public.company_notes;
create policy "no insert when read-only" on public.company_notes as restrictive for insert to authenticated
  with check (not (select public.is_read_only()));
drop policy if exists "no delete when read-only" on public.company_notes;
create policy "no delete when read-only" on public.company_notes as restrictive for delete to authenticated
  using (not (select public.is_read_only()));
revoke all on public.company_notes from anon, authenticated;
grant select, insert, delete on public.company_notes to authenticated;
grant all on public.company_notes to service_role;
commit;
