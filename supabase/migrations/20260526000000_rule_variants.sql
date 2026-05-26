-- Pipeline B variants: per-bill patched rule YAML.
--
-- Mirrors db/migrations/007_rule_variants.sql but in the bills schema
-- with Postgres-native types.

create table if not exists bills.rule_variants (
  id                 uuid primary key default gen_random_uuid(),
  bill_id            uuid not null references bills.bills(id) on delete cascade,
  encoding_id        uuid not null references bills.axiom_encodings(id) on delete cascade,
  file_path          text not null,
  tier               text not null check (tier in ('substitution', 'list', 'structural', 'no_op')),
  patched_rule_names text[] not null default '{}',
  baseline_yaml      text,
  patched_yaml       text,
  diff_summary       text,
  note               text,
  effective_from     date,
  computed_at        timestamptz not null default now(),
  unique (bill_id, file_path)
);

create index if not exists idx_variants_bill on bills.rule_variants(bill_id);
create index if not exists idx_variants_tier on bills.rule_variants(tier);

grant select on bills.rule_variants to anon, authenticated;
grant all    on bills.rule_variants to service_role;
