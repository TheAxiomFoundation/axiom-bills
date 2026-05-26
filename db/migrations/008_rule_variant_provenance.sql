-- Pipeline B variants gain a provenance trail. Tier 1 substitutions
-- come from the deterministic auto-patcher; Tier 2/3 come from an
-- LLM call. We store both the source and the model used so reviewers
-- can decide how much to trust a given variant.
ALTER TABLE rule_variants ADD COLUMN proposed_by TEXT;       -- 'auto' | 'llm'
ALTER TABLE rule_variants ADD COLUMN proposed_model TEXT;    -- e.g. 'claude-sonnet-4-5'
