-- Event date or reported date for findings. Run after 003. Safe to run again.
begin;
alter table public.findings add column if not exists date_type text not null default 'reported';
alter table public.findings drop constraint if exists findings_date_type_check;
alter table public.findings add constraint findings_date_type_check check (date_type in ('event', 'reported'));
commit;
