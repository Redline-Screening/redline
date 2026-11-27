-- Pre-investment companies: screened before investing, not part of the universe. Run after 011. Safe to run again.
begin;
alter table public.holdings drop constraint if exists holdings_type_check;
alter table public.holdings add constraint holdings_type_check check (type in ('holding', 'prospect', 'candidate'));
commit;
