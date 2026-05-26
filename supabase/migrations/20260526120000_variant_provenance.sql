-- Track where a variant's patched YAML came from (auto-patcher vs LLM).
alter table bills.rule_variants
  add column if not exists proposed_by    text,
  add column if not exists proposed_model text;
