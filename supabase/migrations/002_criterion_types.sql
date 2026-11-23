-- Adds criterion types. For databases created before stage 6B.
-- Supabase: SQL Editor -> New query -> paste -> Run. Safe to run again.
begin;

alter table public.criteria add column if not exists type text not null default 'both';

alter table public.criteria drop constraint if exists criteria_type_check;
alter table public.criteria add constraint criteria_type_check check (type in ('revenue', 'conduct', 'both'));

alter table public.criteria alter column threshold drop not null;

-- The breach level is fixed for these types.
update public.criteria set controversy_limit = 'high' where type = 'both' and controversy_limit <> 'high'
  and key is distinct from 'controversial-weapons';
update public.criteria set controversy_limit = 'severe' where type = 'revenue' and controversy_limit <> 'severe';

alter table public.criteria drop constraint if exists criteria_threshold_by_type;
alter table public.criteria add constraint criteria_threshold_by_type check ((type = 'conduct') = (threshold is null));

commit;
