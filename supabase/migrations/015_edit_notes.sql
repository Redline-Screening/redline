-- Investment notes can be edited. Run after 014. Safe to run again.
begin;
alter table public.company_notes add column if not exists updated_at timestamptz;
drop policy if exists "no update when read-only" on public.company_notes;
create policy "no update when read-only" on public.company_notes as restrictive for update to authenticated
  using (not (select public.is_read_only()));
grant update (text, updated_at) on public.company_notes to authenticated;
commit;
