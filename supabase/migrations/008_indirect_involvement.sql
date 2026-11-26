-- Adds "indirect" involvement (supplier to the party involved). Run after 007. Safe to run again.
begin;
alter table public.findings drop constraint if exists findings_involvement_check;
alter table public.findings add constraint findings_involvement_check
  check (involvement in ('company', 'indirect', 'supplier', 'partner', 'unclear'));
commit;
