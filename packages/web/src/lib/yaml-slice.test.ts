/**
 * Unit tests for the YAML rule slicer.
 *
 * Patterns we target are pulled from the real rulespec-us files we ship
 * against — `statutes/26/24.yaml` (single-source rules) and
 * `statutes/26/32.yaml` (compound shorthand sources like
 * `26 USC 32(c)(1)(E), 32(m)`).
 */
import { describe, it, expect } from "vitest";
import { sliceRulesBySource, normalizeSources } from "./yaml-slice";


describe("normalizeSources", () => {
  it("returns a single fully-qualified source as-is", () => {
    expect(normalizeSources("26 USC 32(b)(1)")).toEqual(["26 USC 32(b)(1)"]);
  });

  it("returns multiple fully-qualified sources as-is", () => {
    expect(normalizeSources("26 USC 32(c)(3), 26 USC 152(c)")).toEqual([
      "26 USC 32(c)(3)",
      "26 USC 152(c)",
    ]);
  });

  it("propagates TITLE prefix to comma-separated section shorthand", () => {
    // The shape that triggered the bug: only the first source carries
    // "26 USC", subsequent ones drop it.
    expect(normalizeSources("26 USC 32(c)(1)(E), 32(m)")).toEqual([
      "26 USC 32(c)(1)(E)",
      "26 USC 32(m)",
    ]);
  });

  it("propagates TITLE prefix across multiple shorthand entries", () => {
    expect(
      normalizeSources("26 USC 32(c)(1)(A)-(D), 32(d), 32(e), 32(k)"),
    ).toEqual([
      "26 USC 32(c)(1)(A)-(D)",
      "26 USC 32(d)",
      "26 USC 32(e)",
      "26 USC 32(k)",
    ]);
  });

  it("propagates TITLE+SECTION when entry is a pure subsection ref", () => {
    expect(normalizeSources("26 USC 32(b)(2), (j)")).toEqual([
      "26 USC 32(b)(2)",
      "26 USC 32(j)",
    ]);
  });

  it("handles a section identifier with a trailing letter", () => {
    // §26 USC 25A — letters appear in some IRC section numbers.
    expect(normalizeSources("26 USC 25A(b), 25A(d)")).toEqual([
      "26 USC 25A(b)",
      "26 USC 25A(d)",
    ]);
  });

  it("returns input unchanged when first source isn't USC-shaped", () => {
    // Defensive: if we ever encounter a CFR-only or non-USC source list
    // we shouldn't accidentally rewrite it.
    expect(normalizeSources("7 CFR 273.7(b)(1)")).toEqual(["7 CFR 273.7(b)(1)"]);
  });
});


// ── End-to-end slicer behavior ─────────────────────────────────────

const FIXTURE = `format: rulespec/v1
module:
  source_verification:
    corpus_citation_path: us/statute/26/32
  summary: |-
    EITC rules with mixed source shapes.
rules:
  - name: rule_a_no_source
    kind: data_relation
    data_relation:
      predicate: foo
      arity: 1

  - name: rule_b_single_source
    kind: parameter
    dtype: Money
    source: 26 USC 32(b)(1)
    versions:
      - effective_from: '2018-01-01'
        formula: |-
          7.65

  - name: rule_c_compound_shorthand
    kind: derived
    source: 26 USC 32(c)(1)(E), 32(m)
    versions:
      - effective_from: '2018-01-01'
        formula: |-
          identification_satisfied

  - name: rule_d_multi_qualified
    kind: derived
    source: 26 USC 32(c)(3), 26 USC 152(c)
    versions:
      - effective_from: '2018-01-01'
        formula: |-
          eitc_qualifying_child
`;


describe("sliceRulesBySource", () => {
  it("matches the rule that shares the bill's exact subsection citation", () => {
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(b)(1)");
    expect(out.total).toBe(4);
    expect(out.shown).toBe(1);
    expect(out.filtered).toContain("rule_b_single_source");
    expect(out.filtered).not.toContain("rule_c_compound_shorthand");
  });

  it("matches a rule whose source list drops the TITLE prefix on later items", () => {
    // This is the §32(m) regression case from production.
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(m)");
    expect(out.shown).toBe(1);
    expect(out.filtered).toContain("rule_c_compound_shorthand");
    expect(out.filtered).not.toContain("rule_b_single_source");
  });

  it("matches a parent-section bill against any deeper-subsection rule", () => {
    // Bill amends "26 USC 32" (whole section); every rule in §32 is in scope.
    const out = sliceRulesBySource(FIXTURE, "26 USC 32");
    // rule_a has no source; rules b/c/d have §32 sources. All three should match.
    expect(out.shown).toBe(3);
    expect(out.filtered).toContain("rule_b_single_source");
    expect(out.filtered).toContain("rule_c_compound_shorthand");
    expect(out.filtered).toContain("rule_d_multi_qualified");
  });

  it("matches a rule whose source is a parent of the bill's deeper citation", () => {
    // Bill amends "26 USC 32(b)(1)(A)" — a rule sourced from §32(b)(1)
    // still grounds in the affected text and should be flagged.
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(b)(1)(A)");
    expect(out.shown).toBe(1);
    expect(out.filtered).toContain("rule_b_single_source");
  });

  it("returns the full file with fallback=true when nothing matches", () => {
    // No rule in the fixture sources from §99 — slicer keeps everything
    // but flags fallback=true so the caller can show a clearer message.
    const out = sliceRulesBySource(FIXTURE, "26 USC 99");
    expect(out.fallback).toBe(true);
    expect(out.shown).toBe(out.total);
    expect(out.filtered).toContain("rule_a_no_source");
    expect(out.filtered).toContain("rule_b_single_source");
  });

  it("sets fallback=false when at least one rule matches", () => {
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(m)");
    expect(out.fallback).toBe(false);
  });

  it("sets fallback=false when every rule legitimately matches a parent citation", () => {
    // Bill amends the whole §32 — every rule in §32.yaml is in scope and
    // it's NOT a fallback. The slicer kept everything because everything
    // genuinely overlapped.
    const out = sliceRulesBySource(FIXTURE, "26 USC 32");
    expect(out.fallback).toBe(false);
    expect(out.shown).toBe(3);
  });

  it("handles PyYAML safe_dump style (no indent before dash)", () => {
    // The LLM reencoder emits via PyYAML which puts list items at
    // column 0 instead of the handwritten 2-space convention. Slicer
    // must filter these correctly too.
    const pyDumpStyle = [
      "format: rulespec/v1",
      "rules:",
      "- name: rule_a",
      "  kind: parameter",
      "  source: 26 USC 32(b)(1)",
      "  versions:",
      "  - effective_from: '2018-01-01'",
      "    formula: '7.65'",
      "- name: rule_b",
      "  kind: derived",
      "  source: 26 USC 32(c)(1)(E), 32(m)",
      "  versions:",
      "  - effective_from: '2018-01-01'",
      "    formula: identification_satisfied",
      "",
    ].join("\n");
    const out = sliceRulesBySource(pyDumpStyle, "26 USC 32(m)");
    expect(out.fallback).toBe(false);
    expect(out.shown).toBe(1);
    expect(out.filtered).toContain("rule_b");
    expect(out.filtered).not.toContain("rule_a");
  });

  it("returns input unchanged when there's no `rules:` block", () => {
    const yaml = "format: rulespec/v1\nmodule:\n  summary: hello\n";
    const out = sliceRulesBySource(yaml, "26 USC 32");
    expect(out.filtered).toBe(yaml);
    expect(out.total).toBe(0);
    expect(out.shown).toBe(0);
  });

  it("preserves the preamble (format, module, summary) on filter", () => {
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(m)");
    expect(out.filtered).toContain("format: rulespec/v1");
    expect(out.filtered).toContain("EITC rules with mixed source shapes");
  });

  it("does not match data_relation rules with no source", () => {
    // rule_a has no `source:` field; can't be auto-matched. The slicer
    // skips it, but the file as a whole isn't reduced to zero because
    // other rules match.
    const out = sliceRulesBySource(FIXTURE, "26 USC 32(b)(1)");
    expect(out.filtered).not.toContain("rule_a_no_source");
  });
});
