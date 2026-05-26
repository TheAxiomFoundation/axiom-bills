#!/usr/bin/env node
/**
 * Batch validation for the YAML rule slicer.
 *
 * Pulls every variant in Supabase, runs sliceRulesBySource against
 * each (bill, file_path, section.citation) triple, and reports
 * shown/total reduction plus any anomalies.
 *
 * The slicer logic is duplicated here from src/lib/yaml-slice.ts so
 * the script stays standalone-runnable without a TS compiler. The
 * vitest suite (npm test) is the source of truth for correctness;
 * this script is for live-data spot-checking.
 */

// ── Slicer (mirror of src/lib/yaml-slice.ts) ──────────────────────

function normalizeSources(raw) {
  const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) return [];
  const first = parts[0];
  const m = first.match(/^(\d+\s+USC\s+)(\d+[A-Za-z]?)/);
  if (!m) return parts;
  const title = m[1];
  const titleSection = title + m[2];
  return parts.map((p, i) => {
    if (i === 0) return p;
    if (/^\d+\s+USC\s+/.test(p)) return p;
    if (/^\d+/.test(p)) return title + p;
    if (/^\(/.test(p)) return titleSection + p;
    return p;
  });
}

function sourceOverlaps(block, citation) {
  const m = block.match(/^ {4}source:\s*(.+)$/m);
  if (!m) return false;
  const sources = normalizeSources(m[1]);
  return sources.some((s) => s.startsWith(citation) || citation.startsWith(s));
}

function sliceRulesBySource(yamlText, citation) {
  const lines = yamlText.split("\n");
  const rulesLineIdx = lines.findIndex((l) => /^rules\s*:\s*$/.test(l));
  if (rulesLineIdx === -1) return { filtered: yamlText, total: 0, shown: 0, fallback: false };

  const preamble = lines.slice(0, rulesLineIdx + 1).join("\n");
  const afterRules = lines.slice(rulesLineIdx + 1);

  const ruleStarts = [];
  for (let i = 0; i < afterRules.length; i++) {
    if (/^ {2}- name:/.test(afterRules[i])) ruleStarts.push(i);
  }
  if (ruleStarts.length === 0) return { filtered: yamlText, total: 0, shown: 0, fallback: false };

  const ruleBlocks = [];
  for (let r = 0; r < ruleStarts.length; r++) {
    const start = ruleStarts[r];
    const end = r + 1 < ruleStarts.length ? ruleStarts[r + 1] : afterRules.length;
    ruleBlocks.push(afterRules.slice(start, end).join("\n"));
  }
  const total = ruleBlocks.length;
  const kept = ruleBlocks.filter((b) => sourceOverlaps(b, citation));
  if (kept.length === 0) return { filtered: yamlText, total, shown: total, fallback: true };
  return {
    filtered: preamble + "\n" + kept.join("").trimEnd() + "\n",
    total,
    shown: kept.length,
    fallback: false,
  };
}

// ── Live-data validation ──────────────────────────────────────────

const SUPABASE_URL = process.env.SUPABASE_URL;
const ANON = process.env.SUPABASE_ANON_KEY;
if (!SUPABASE_URL || !ANON) {
  console.error("Set SUPABASE_URL and SUPABASE_ANON_KEY env vars.");
  process.exit(1);
}
const headers = { apikey: ANON, Authorization: `Bearer ${ANON}`, "Accept-Profile": "bills" };

async function fetchVariants() {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/rule_variants?select=bill_id,file_path,tier,baseline_yaml,axiom_encodings:encoding_id(citation)`,
    { headers },
  );
  return r.json();
}

async function fetchDiffs(billId) {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/bills?select=diffs&id=eq.${billId}`, { headers },
  );
  const rows = await r.json();
  return rows[0]?.diffs ?? null;
}

const variants = await fetchVariants();
console.log(`Loaded ${variants.length} variants from Supabase\n`);

const billCache = new Map();
async function diffsFor(billId) {
  if (!billCache.has(billId)) billCache.set(billId, await fetchDiffs(billId));
  return billCache.get(billId);
}

const flags = { totalDropped: [], keptAll: [], fallback: [], noRules: [] };
let totalShown = 0;
let totalRules = 0;
let processed = 0;

for (const v of variants) {
  if (!v.baseline_yaml) continue;
  const diffs = await diffsFor(v.bill_id);
  if (!diffs) continue;

  const matchingSections = diffs.sections.filter(
    (s) => s.encoding?.file_path === v.file_path,
  );
  if (matchingSections.length === 0) continue;

  for (const section of matchingSections) {
    const out = sliceRulesBySource(v.baseline_yaml, section.citation);
    processed += 1;
    totalShown += out.shown;
    totalRules += out.total;
    const pct = out.total > 0 ? ((out.shown / out.total) * 100).toFixed(0) : "—";
    const tag = `${v.file_path} @ ${section.citation}  ${out.shown}/${out.total} (${pct}%)`;
    if (out.total === 0) flags.noRules.push(tag);
    else if (out.fallback) flags.fallback.push(tag);
    else if (out.shown === out.total && out.total > 3)
      flags.keptAll.push(tag);
    else if (out.shown === 0) flags.totalDropped.push(tag);
    console.log(`  ${tag}`);
  }
}

console.log("\n──── summary ────");
console.log(`sections processed:     ${processed}`);
console.log(`total rules in YAMLs:   ${totalRules}`);
console.log(`rules surfaced:         ${totalShown}`);
console.log(`aggregate reduction:    ${(100 * (1 - totalShown / totalRules)).toFixed(1)}%`);

if (flags.totalDropped.length) {
  console.log(`\n⚠  ${flags.totalDropped.length} section(s) where the slicer dropped to 0 — bug:`);
  flags.totalDropped.forEach((t) => console.log(`     ${t}`));
}
if (flags.keptAll.length) {
  console.log(`\nℹ  ${flags.keptAll.length} section(s) where the slicer kept 100% (legitimate parent-citation overlap):`);
  flags.keptAll.forEach((t) => console.log(`     ${t}`));
}
if (flags.fallback.length) {
  console.log(`\nℹ  ${flags.fallback.length} section(s) where NO rule grounds in the citation (UI now shows a specific message):`);
  flags.fallback.forEach((t) => console.log(`     ${t}`));
}
if (flags.noRules.length) {
  console.log(`\nℹ  ${flags.noRules.length} YAML(s) with no rules block (preamble-only):`);
  flags.noRules.forEach((t) => console.log(`     ${t}`));
}
if (!flags.totalDropped.length && !flags.keptAll.length && !flags.noRules.length) {
  console.log("\n✓ no anomalies — every section narrowed cleanly.");
}
