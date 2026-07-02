// Slice a rulespec YAML to just the rules whose `source:` overlaps with a
// target citation. Used in the diff section panel so the "Current" /
// "If enacted" tabs focus on the rules the bill actually touches,
// rather than rendering every rule in the file.
//
// We do this with a line-based scan instead of pulling in a YAML parser
// — rulespec files use a stable shape (`rules:` list of top-level
// dicts indented two spaces) and we only need to extract per-rule
// blocks, not interpret them.

export type SlicedYaml = {
  filtered: string;
  total: number;
  shown: number;
  /** True when no rule's source overlapped with the citation — the
   * slicer fell back to the unfiltered file. Callers should show a
   * "no rule grounds in this subsection" message rather than dumping
   * the whole YAML. */
  fallback: boolean;
};

/** Return a YAML containing only rules whose `source:` overlaps with
 * `citation`. If nothing matches, returns the whole file with
 * `fallback: true` so the caller can render a clearer empty state. */
export function sliceRulesBySource(yamlText: string, citation: string): SlicedYaml {
  const lines = yamlText.split("\n");
  const rulesLineIdx = lines.findIndex((l) => /^rules\s*:\s*$/.test(l));
  if (rulesLineIdx === -1) {
    return { filtered: yamlText, total: 0, shown: 0, fallback: false };
  }

  const preamble = lines.slice(0, rulesLineIdx + 1).join("\n");
  const afterRules = lines.slice(rulesLineIdx + 1);

  // Top-level rule entries start with `- name:`. Two YAML conventions:
  //   handwritten rulespec: "  - name:" (2-space indent)
  //   PyYAML safe_dump:     "- name:"   (no indent)
  // Accept either. Nested `- path:` inside atoms uses 4+-space indent
  // and starts with "path:", not "name:", so no collision.
  const ruleStarts: number[] = [];
  for (let i = 0; i < afterRules.length; i++) {
    if (/^ {0,2}- name:/.test(afterRules[i])) ruleStarts.push(i);
  }
  if (ruleStarts.length === 0) {
    return { filtered: yamlText, total: 0, shown: 0, fallback: false };
  }

  const ruleBlocks: string[] = [];
  for (let r = 0; r < ruleStarts.length; r++) {
    const start = ruleStarts[r];
    const end = r + 1 < ruleStarts.length ? ruleStarts[r + 1] : afterRules.length;
    ruleBlocks.push(afterRules.slice(start, end).join("\n"));
  }
  const total = ruleBlocks.length;

  const kept = ruleBlocks.filter((block) => sourceOverlaps(block, citation));
  if (kept.length === 0) {
    return { filtered: yamlText, total, shown: total, fallback: true };
  }
  return {
    filtered: preamble + "\n" + kept.join("\n").trimEnd() + "\n",
    total,
    shown: kept.length,
    fallback: false,
  };
}

/** Collapse citation format drift: rulespec rule sources aren't uniform
 * ('20 U.S.C. 1070a' vs '20 USC 1070a', stray '§'), and prefix
 * comparison silently fails across the dotted form — which rendered
 * "no rule in this file grounds in 20 USC 1070a" for a file whose three
 * rules all ground in 1070a(b)(5). */
export function normCitation(c: string): string {
  return c
    .replace(/\bU\.\s*S\.\s*C\./g, "USC")
    .replace(/\bC\.\s*F\.\s*R\./g, "CFR")
    // 'IRC section 63(c)(5)' — the IRC is codified verbatim as Title 26.
    // Keep in sync with citation_scope.normalize_citation (Python).
    .replace(/\bIRC\s+(?:section\s+|§\s*)?(?=\d)/g, "26 USC ")
    .replace(/§/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Does this rule block's `source:` line overlap with the target citation?
 * Accepts either 2-space (PyYAML dump) or 4-space (handwritten) indent. */
function sourceOverlaps(block: string, citation: string): boolean {
  const m = block.match(/^ {2,4}source:\s*(.+)$/m);
  if (!m) return false;
  const target = normCitation(citation);
  const sources = normalizeSources(normCitation(m[1]));
  return sources.some((s) => s.startsWith(target) || target.startsWith(s));
}

/** Expand the rulespec convention where comma-separated sources share a
 * leading "TITLE USC SECTION" — only the first source carries it in
 * full, and subsequent ones drop the prefix (e.g. "26 USC 32(c)(1)(E),
 * 32(m), (j)"). We rebuild fully-qualified citations so the overlap
 * check above doesn't miss the shorthand entries. */
export function normalizeSources(raw: string): string[] {
  const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) return [];

  const first = parts[0];
  // Extract "TITLE USC SECTION" out of the first source so we can splice
  // it onto any short-form subsequent entries.
  const m = first.match(/^(\d+\s+USC\s+)(\d+[A-Za-z]?)/);
  if (!m) return parts;
  const title = m[1];           // "26 USC "
  const titleSection = title + m[2]; // "26 USC 32"

  return parts.map((p, i) => {
    if (i === 0) return p;
    if (/^\d+\s+USC\s+/.test(p)) return p;           // already qualified
    if (/^\d+/.test(p)) return title + p;            // "32(j)" → "26 USC 32(j)"
    if (/^\(/.test(p)) return titleSection + p;      // "(j)"   → "26 USC 32(j)"
    return p;
  });
}
