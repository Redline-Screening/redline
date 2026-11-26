-- Sourced revenue estimates, involvement, evidence, legal status, date precision.
-- Run after 005. Safe to run again.
begin;

alter table public.scores add column if not exists exposure_sourced boolean not null default false;
alter table public.scores add column if not exists exposure_sources jsonb not null default '[]'::jsonb;
alter table public.scores add column if not exists exposure_quote text;

alter table public.findings add column if not exists involvement text;      -- null: not classified
alter table public.findings add column if not exists evidence text;
alter table public.findings add column if not exists legal_status text;
alter table public.findings add column if not exists date_precision text not null default 'day';

alter table public.findings drop constraint if exists findings_involvement_check;
alter table public.findings add constraint findings_involvement_check check (involvement in ('company', 'supplier', 'partner', 'unclear'));
alter table public.findings drop constraint if exists findings_evidence_check;
alter table public.findings add constraint findings_evidence_check check (evidence in ('proven', 'alleged'));
alter table public.findings drop constraint if exists findings_legal_check;
alter table public.findings add constraint findings_legal_check check (legal_status in ('none', 'open', 'settled', 'dismissed', 'against', 'unclear'));
alter table public.findings drop constraint if exists findings_precision_check;
alter table public.findings add constraint findings_precision_check check (date_precision in ('day', 'month', 'year'));

update public.criteria set controversy_limit = 'high'
where key in ('child-labour', 'forced-labour') and type = 'conduct' and controversy_limit = 'medium';

commit;
