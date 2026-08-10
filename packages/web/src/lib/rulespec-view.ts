// Structured view-model for the RuleSpec panel: parse a rulespec YAML
// into per-rule cards the diff panel can render readably, instead of
// dumping raw YAML into a <pre>.
//
// Everything here is pure and unit-tested; the React component
// (RuleSpecRules.tsx) only renders what this module produces. The
// `yaml` dependency is pulled in lazily with the component (React.lazy)
// so it stays out of the main bundle.

import { parse as parseYaml } from "yaml";
import type { AmendmentOp } from "./api";
import { normCitation, normalizeSources } from "./yaml-slice";

export type RuleAtom = {
  kind: string; // formula | condition | exception | amount | import | …
  excerpt: string | null; // verbatim statute quote (source.excerpt|text)
  importTarget: string | null; // "us:statutes/26/25E#tentative_…" for kind=import
  /** True when a bill op strikes text inside this atom's quote — the
   *  strongest "this exact code is affected" signal we have. */
  struck: boolean;
};

export type RuleVersion = {
  effectiveFrom: string | null;
  formula: string; // pretty-printed
};

export type RuleCard = {
  name: string;
  kind: string;
  entity: string | null;
  dtype: string | null;
  period: string | null;
  source: string;
  /** Source citations that intersect the amended citation. */
  matchedSources: string[];
  atoms: RuleAtom[];
  versions: RuleVersion[];
};

export type ParsedRules = {
  cards: RuleCard[]; // rules grounding in the amended citation
  otherCount: number; // rules in the file that don't
  total: number;
  error: boolean; // YAML didn't parse / no rules list — caller falls back to raw
};

const collapse = (s: string) => s.replace(/\s+/g, " ").trim();
const normQuote = (s: string) => collapse(s).toLowerCase();

/** Does a bill op strike (or insert over) text quoted in this excerpt?
 *  Excerpts may elide with "..." — compare each elided fragment
 *  separately so "No credit ... after September 30, 2025" still matches
 *  a needle of "September 30, 2025". */
export function opStrikesExcerpt(excerpt: string, ops: AmendmentOp[]): boolean {
  const fragments = excerpt
    .split(/\.{3,}|…/)
    .map(normQuote)
    .filter((f) => f.length >= 4);
  if (fragments.length === 0) return false;
  return ops.some((op) => {
    const needle = normQuote(op.needle ?? "");
    if (needle.length < 4) return false;
    return fragments.some(
      (frag) => frag.includes(needle) || needle.includes(frag),
    );
  });
}

/** Pretty-print a rulespec formula string. The encoder emits YAML-folded
 *  one-liners ("if a and b and not c: x else: 0"); break them into an
 *  indented if/and/else layout. Non-conditional formulas (bare numbers,
 *  min(...) expressions) are just whitespace-collapsed. */
export function formatFormula(raw: string): string {
  const s = collapse(raw);
  if (!/^if\s/.test(s)) return s;

  const elseSplit = s.split(/\s+else:\s*/);
  const ifPart = elseSplit[0];
  const elsePart = elseSplit.length > 1 ? elseSplit.slice(1).join(" else: ") : null;

  // "if COND: RESULT" — the first ": " after the condition separates the
  // then-branch (identifiers/conditions themselves never contain ": ").
  const m = ifPart.match(/^if\s+(.*?):\s*(.*)$/);
  if (!m) return s;
  const [, cond, thenBranch] = m;
  const condLines = cond
    .split(/\s+(?=(?:and|or)\s)/)
    .map((c, i) => (i === 0 ? `if ${c}` : `   ${c}`));
  const lines = [...condLines];
  lines[lines.length - 1] += ":";
  lines.push(`  ${thenBranch}`);
  if (elsePart !== null) {
    lines.push("else:");
    lines.push(`  ${elsePart}`);
  }
  return lines.join("\n");
}

function sourceMatches(sourceStr: string, citation: string): string[] {
  const target = normCitation(citation);
  return normalizeSources(normCitation(sourceStr)).filter(
    (s) => s.startsWith(target) || target.startsWith(s),
  );
}

/** Parse a rulespec YAML and build cards for the rules grounding in
 *  `citation`, with each atom checked against the bill's ops. */
export function buildRuleCards(
  yamlText: string,
  citation: string,
  ops: AmendmentOp[],
): ParsedRules {
  let doc: unknown;
  try {
    doc = parseYaml(yamlText);
  } catch {
    return { cards: [], otherCount: 0, total: 0, error: true };
  }
  const rules = (doc as { rules?: unknown })?.rules;
  if (!Array.isArray(rules) || rules.length === 0) {
    return { cards: [], otherCount: 0, total: 0, error: true };
  }

  const cards: RuleCard[] = [];
  let otherCount = 0;
  for (const r of rules) {
    if (!r || typeof r !== "object") continue;
    const rule = r as Record<string, any>;
    const source = String(rule.source ?? "");
    const matched = source ? sourceMatches(source, citation) : [];
    if (matched.length === 0) {
      otherCount++;
      continue;
    }

    const rawAtoms = rule.metadata?.proof?.atoms;
    const atoms: RuleAtom[] = Array.isArray(rawAtoms)
      ? rawAtoms
          .filter((a: unknown) => a && typeof a === "object")
          .map((a: Record<string, any>) => {
            const excerpt = a.source?.excerpt ?? a.source?.text ?? null;
            return {
              kind: String(a.kind ?? ""),
              excerpt: excerpt ? collapse(String(excerpt)) : null,
              importTarget: a.import?.target ? String(a.import.target) : null,
              struck: excerpt
                ? opStrikesExcerpt(String(excerpt), ops)
                : false,
            };
          })
      : [];

    const rawVersions = rule.versions;
    const versions: RuleVersion[] = Array.isArray(rawVersions)
      ? rawVersions
          .filter((v: unknown) => v && typeof v === "object")
          .map((v: Record<string, any>) => ({
            effectiveFrom: v.effective_from ? String(v.effective_from) : null,
            formula: formatFormula(String(v.formula ?? "")),
          }))
      : [];

    cards.push({
      name: String(rule.name ?? ""),
      kind: String(rule.kind ?? ""),
      entity: rule.entity ? String(rule.entity) : null,
      dtype: rule.dtype ? String(rule.dtype) : null,
      period: rule.period ? String(rule.period) : null,
      source,
      matchedSources: matched,
      atoms,
      versions,
    });
  }
  return { cards, otherCount, total: cards.length + otherCount, error: false };
}
