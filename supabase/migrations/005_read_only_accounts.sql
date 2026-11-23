-- Read-only accounts (demo). Run after 004. Safe to run again.
begin;

create or replace function public.is_read_only() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.accounts a where a.user_id = auth.uid() and a.read_only);
$$;
revoke execute on function public.is_read_only() from public, anon;
grant execute on function public.is_read_only() to authenticated;

-- Restrictive policies apply in addition to the "own rows" policies.
do $$
declare
  t text;
begin
  foreach t in array array['workspaces', 'holdings', 'criteria', 'scores', 'alerts', 'findings'] loop
    execute format('drop policy if exists "no insert when read-only" on public.%I', t);
    execute format('drop policy if exists "no update when read-only" on public.%I', t);
    execute format('drop policy if exists "no delete when read-only" on public.%I', t);
    execute format('create policy "no insert when read-only" on public.%I as restrictive for insert to authenticated with check (not (select public.is_read_only()))', t);
    execute format('create policy "no update when read-only" on public.%I as restrictive for update to authenticated using (not (select public.is_read_only()))', t);
    execute format('create policy "no delete when read-only" on public.%I as restrictive for delete to authenticated using (not (select public.is_read_only()))', t);
  end loop;
end $$;

commit;
