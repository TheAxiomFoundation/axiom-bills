/**
 * Unit tests for the RuleSpec card view-model. The fixture mirrors the
 * real statutes/26/25E.yaml shape — module preamble with deferred
 * outputs, excerpt-format proof atoms, an import atom, and a folded
 * one-liner if/else formula — as amended by S.5215 (termination date
 * strike-insert).
 */
import { describe, it, expect } from "vitest";
import type { AmendmentOp } from "./api";
import {
  buildRuleCards,
  formatFormula,
  opStrikesExcerpt,
} from "./rulespec-view";

const FIXTURE = `format: rulespec/v1
module:
  source_verification:
    corpus_citation_path: us/statute/26/25E
  deferred_outputs:
  - output: us:statutes/26/25E/b#credit_allowed_after_magi_limitation
    reason: Long prose that must never surface in the cards.
  summary: Section 25E allows a credit.
rules:
- name: previously_owned_clean_vehicle_credit_cap
  kind: parameter
  dtype: Money
  source: 26 USC 25E(a)(1)
  versions:
  - effective_from: '2026-01-01'
    formula: '4000'
- name: previously_owned_clean_vehicle_credit_allowed_before_magi_limitation
  kind: derived
  entity: TaxUnit
  dtype: Money
  period: Year
  source: 26 USC 25E(a), 26 USC 25E(d), 26 USC 25E(g)
  metadata:
    proof:
      atoms:
      - path: versions[0].formula
        kind: exception
        source:
          corpus_citation_path: us/statute/26/25E
          excerpt: No credit shall be allowed ... with respect to any vehicle acquired
            after September 30, 2025
      - path: versions[0].formula
        kind: condition
        source:
          corpus_citation_path: us/statute/26/25E
          excerpt: unless the taxpayer includes the vehicle identification number
      - path: versions[0].formula
        kind: import
        import:
          target: us:statutes/26/25E#tentative_previously_owned_clean_vehicle_credit
          output: tentative_previously_owned_clean_vehicle_credit
  versions:
  - effective_from: '2026-01-01'
    formula: 'if taxpayer_is_qualified_buyer and vehicle_identification_number_included_on_return
      and not vehicle_acquired_after_termination_date: tentative_previously_owned_clean_vehicle_credit
      else: 0'
`;

const STRIKE_OP: AmendmentOp = {
  kind: "strike-insert",
  needle: "September 30, 2025",
  payload: "December 31, 2031",
  raw: 'by striking "September 30, 2025" and inserting "December 31, 2031"',
};

describe("opStrikesExcerpt", () => {
  it("matches a needle inside an elided excerpt fragment", () => {
    expect(
      opStrikesExcerpt(
        "No credit shall be allowed ... after September 30, 2025",
        [STRIKE_OP],
      ),
    ).toBe(true);
  });

  it("ignores unrelated excerpts and trivial needles", () => {
    expect(
      opStrikesExcerpt("unless the taxpayer includes the VIN", [STRIKE_OP]),
    ).toBe(false);
    expect(
      opStrikesExcerpt("No credit shall be allowed", [
        { ...STRIKE_OP, needle: "a" },
      ]),
    ).toBe(false);
    expect(opStrikesExcerpt("......", [STRIKE_OP])).toBe(false);
  });
});

describe("formatFormula", () => {
  it("breaks a folded if/and/else one-liner into indented lines", () => {
    const out = formatFormula(
      "if a and b\n      and not c: result_value else: 0",
    );
    expect(out.split("\n")).toEqual([
      "if a",
      "   and b",
      "   and not c:",
      "  result_value",
      "else:",
      "  0",
    ]);
  });

  it("leaves non-conditional formulas as a collapsed single line", () => {
    expect(formatFormula("min(\n    cap,\n    rate * price\n)")).toBe(
      "min( cap, rate * price )",
    );
    expect(formatFormula("4000")).toBe("4000");
  });
});

describe("buildRuleCards", () => {
  it("keeps only rules grounding in the amended citation", () => {
    const out = buildRuleCards(FIXTURE, "26 USC 25E(g)", [STRIKE_OP]);
    expect(out.error).toBe(false);
    expect(out.total).toBe(2);
    expect(out.otherCount).toBe(1);
    expect(out.cards.map((c) => c.name)).toEqual([
      "previously_owned_clean_vehicle_credit_allowed_before_magi_limitation",
    ]);
  });

  it("marks the atom whose quote the bill strikes, and only that one", () => {
    const [card] = buildRuleCards(FIXTURE, "26 USC 25E(g)", [STRIKE_OP]).cards;
    const byKind = Object.fromEntries(card.atoms.map((a) => [a.kind, a]));
    expect(byKind.exception.struck).toBe(true);
    expect(byKind.exception.excerpt).toContain("after September 30, 2025");
    expect(byKind.condition.struck).toBe(false);
    expect(byKind.import.importTarget).toContain(
      "#tentative_previously_owned_clean_vehicle_credit",
    );
  });

  it("pretty-prints the folded formula and keeps effective_from", () => {
    const [card] = buildRuleCards(FIXTURE, "26 USC 25E(g)", []).cards;
    expect(card.versions).toHaveLength(1);
    expect(card.versions[0].effectiveFrom).toBe("2026-01-01");
    expect(card.versions[0].formula).toContain("if taxpayer_is_qualified_buyer\n");
    expect(card.versions[0].formula).toContain(
      "\n   and not vehicle_acquired_after_termination_date:",
    );
    expect(card.versions[0].formula).toContain("\nelse:\n  0");
  });

  it("never leaks the module preamble into the cards", () => {
    const out = buildRuleCards(FIXTURE, "26 USC 25E(g)", []);
    const dump = JSON.stringify(out);
    expect(dump).not.toContain("deferred_outputs");
    expect(dump).not.toContain("Long prose that must never surface");
  });

  it("flags unparseable YAML so the caller can fall back to raw text", () => {
    expect(buildRuleCards(": not yaml : [", "26 USC 1", []).error).toBe(true);
    expect(buildRuleCards("format: rulespec/v1\n", "26 USC 1", []).error).toBe(true);
  });
});
