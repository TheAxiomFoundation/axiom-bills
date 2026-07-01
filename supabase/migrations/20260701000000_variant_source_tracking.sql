-- Mirror of db/migrations/056_variant_source_tracking.sql, plus a
-- downstream consumption surface for the patched YAML.

alter table bills.rule_variants
  add column if not exists source_ops_fingerprint text,
  add column if not exists source_text_sha256     text;

-- Downstream apps (and an eventual rulespec-us PR bot) need "the latest
-- patched YAML per encoded file, with enough bill context to decide
-- whether to act on it" without re-deriving the join. One row per
-- (bill, file); consumers filter on bill_status themselves (e.g.
-- bill_status in ('enacted','signed') to only apply law that passed).
create or replace view bills.current_rule_patches as
select
  v.id,
  b.jurisdiction,
  b.number            as bill_number,
  b.title             as bill_title,
  b.current_status    as bill_status,
  b.current_status_at as bill_status_at,
  e.repo,
  v.file_path,
  e.citation,
  v.tier,
  v.patched_rule_names,
  v.patched_yaml,
  v.diff_summary,
  v.effective_from,
  v.proposed_by,
  v.proposed_model,
  v.source_ops_fingerprint,
  v.computed_at
from bills.rule_variants v
join bills.bills b            on b.id = v.bill_id
left join bills.axiom_encodings e on e.id = v.encoding_id
where v.patched_yaml is not null;

grant select on bills.current_rule_patches to anon, authenticated;
grant select on bills.current_rule_patches to service_role;
