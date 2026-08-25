-- Mirror of db/migrations/059_encoding_graphs.sql, in the bills schema
-- with Postgres-native types.
--
-- One RuleSpec dependency-graph JSON snapshot per rulespec-* repo,
-- built by `precompute-graph` and pushed by sync-supabase. The web
-- Impact tab reads it directly; the bill overlay is joined client-side.

create table if not exists bills.encoding_graphs (
  repo            text primary key,
  graph           jsonb not null,
  generated_from  text,
  generated_at    timestamptz not null default now()
);

grant select on bills.encoding_graphs to anon, authenticated;
grant all    on bills.encoding_graphs to service_role;
