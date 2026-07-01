// Frontend data layer — talks to Supabase directly via @supabase/supabase-js.
// The shapes below are the same the FastAPI service used to return so
// page components don't change. All the formatting (matched_encodings,
// matched_corpus, sponsors-as-objects, action+version coalescing) is
// derived client-side from the Supabase rows.

import { supabase } from "./supabase";

export type Coverage = "full" | "stub" | "planned";

export type Jurisdiction = {
  code: string;
  name: string;
  level: "federal" | "state";
  coverage: Coverage;
  source_url: string;
  bill_count: number;
  enacted_count: number;
  last_scraped_at: string | null;
};

export type CoverageSummary = {
  totals: { full: number; stub: number; planned: number };
  states: { code: string; name: string; coverage: Coverage; source_url: string }[];
};

export type BillKind =
  | "substantive" | "placeholder" | "ceremonial"
  | "appropriations" | "procedural" | "vehicle" | "unknown";

export const ALL_KINDS: BillKind[] = [
  "substantive", "placeholder", "ceremonial",
  "appropriations", "procedural", "vehicle", "unknown",
];

export type Relevance = "any" | "touches_corpus" | "touches_rulespec";

export type NormalizedStatus =
  | "introduced" | "in_committee" | "passed_chamber" | "passed_both"
  | "enrolled" | "signed" | "enacted" | "vetoed" | "veto_overridden"
  | "failed" | "unknown";

export type MatchedEncoding = {
  repo: string;
  kind: "statute" | "regulation" | "policy";
  citation: string;
  file_path: string;
  github_url: string;
};

export type MatchedCorpus = {
  citation: string;
  citation_path: string;
  heading: string | null;
  axiom_url: string;
};

export type BillRow = {
  id: string;
  number: string;
  title: string | null;
  chamber: string;
  kind: BillKind;
  current_status: NormalizedStatus;
  current_status_at: string | null;
  latest_action_at: string | null;
  first_seen_at: string;
  source_url: string;
  session_name: string;
  matched_encodings: MatchedEncoding[];
  matched_corpus: MatchedCorpus[];
};

export type KindCounts = Record<BillKind, number>;

export type BillVersionFormat = { format: string; source_url: string; label: string };

export type BillAction = {
  occurred_at: string;
  chamber: string | null;
  action_text: string;
  normalized_status: NormalizedStatus | null;
  source_url: string | null;
  versions: BillVersionFormat[];
};

export type BillVersion = {
  label: string;
  source_url: string;
  format: string;
  fetched_at: string | null;
};

export type UnclaimedVersion = {
  stage: string;
  stage_label: string;
  formats: BillVersionFormat[];
};

export type BillDetail = BillRow & {
  jurisdiction: string;
  jurisdiction_name: string;
  kind: BillKind;
  summary: string | null;
  subjects: string[];
  sponsors: { name: string; role?: string; party?: string; district?: string }[];
  actions: BillAction[];
  versions: BillVersion[];
  unclaimed_versions: UnclaimedVersion[];
  texts: { version_label: string; format: string; text: string; fetched_at: string }[];
};

export type ExtractedCitation = {
  raw: string;
  citation: string;
  source: "title" | "summary" | "text" | "action";
};

export type AxiomEncoding = {
  jurisdiction: string;
  repo: string;
  kind: "statute" | "regulation" | "policy";
  citation: string;
  file_path: string;
};

export type DiffBlock = { kind: "equal" | "add" | "remove"; text: string };

export type AmendmentOp = {
  kind: "strike-insert" | "add-end" | "replace-all" | "strike";
  needle: string;
  payload: string;
  raw: string;
};

export type BillDiffSection = {
  citation: string;
  in_corpus: boolean;
  exact_corpus_match: boolean;
  sliced_subsection: boolean;
  matched_corpus_path: string | null;
  heading: string | null;
  citation_path?: string;
  current_text: string | null;
  applied_text: string | null;
  diff: DiffBlock[];
  applied_ops: AmendmentOp[];
  unapplied_ops: AmendmentOp[];
  has_rulespec: boolean;
  encoding: {
    repo: string;
    kind: "statute" | "regulation" | "policy";
    citation: string;
    file_path: string;
    github_url: string;
  } | null;
  axiom_url: string | null;
  source_url: string | null;
};

export type BillDiffs = { sections: BillDiffSection[] };

export type VariantTier = "substitution" | "list" | "structural" | "no_op";

export type RuleVariant = {
  id: string;
  file_path: string;
  tier: VariantTier;
  patched_rule_names: string[];
  baseline_yaml: string | null;
  patched_yaml: string | null;
  diff_summary: string | null;
  note: string | null;
  effective_from: string | null;
  proposed_by: "auto" | "llm" | null;
  proposed_model: string | null;
  encoding: {
    repo: string;
    citation: string;
    github_url: string;
  } | null;
};

export type RecentRow = {
  id: string;
  jurisdiction: string;
  jurisdiction_name: string;
  jurisdiction_level: "federal" | "state";
  number: string;
  title: string | null;
  current_status: NormalizedStatus;
  current_status_at: string | null;
  source_url: string;
};

const AXIOM_APP_URL =
  (import.meta.env.VITE_AXIOM_APP_URL as string | undefined) ??
  "https://app.axiom-foundation.org";

// ─── Internal helpers ───────────────────────────────────────────────

function buildMatchedForBill(diffs: BillDiffs | null) {
  // matched_encodings: an encoding counts as "touched" when the bill
  // has a PARSED amendment op (applied or unapplied) against a section
  // whose citation matches. A bill that merely cites §X in a findings/
  // definitions clause doesn't force a re-encode; but an instruction
  // the applier couldn't verify against corpus text is still a real
  // amendment and must not vanish from the trigger.
  const matched_encodings: MatchedEncoding[] = [];
  const seenE = new Set<string>();
  if (diffs) {
    for (const sec of diffs.sections) {
      if (!sec.encoding) continue;
      if (sec.applied_ops.length === 0 && sec.unapplied_ops.length === 0) continue;
      if (seenE.has(sec.encoding.file_path)) continue;
      seenE.add(sec.encoding.file_path);
      matched_encodings.push(sec.encoding);
    }
  }

  // matched_corpus: corpus rows the bill amends (parsed ops, applied or
  // not). Pure cross-references still don't count.
  const matched_corpus: MatchedCorpus[] = [];
  const seenC = new Set<string>();
  if (diffs) {
    for (const sec of diffs.sections) {
      if (!sec.in_corpus || !sec.citation_path) continue;
      if (sec.applied_ops.length === 0 && sec.unapplied_ops.length === 0) continue;
      if (seenC.has(sec.citation_path)) continue;
      seenC.add(sec.citation_path);
      matched_corpus.push({
        citation: sec.citation,
        citation_path: sec.citation_path,
        heading: sec.heading,
        axiom_url: sec.axiom_url ?? `${AXIOM_APP_URL}/${sec.citation_path}`,
      });
    }
  }

  return { matched_encodings, matched_corpus };
}

// ─── Top-level API ──────────────────────────────────────────────────

async function jurisdictions(): Promise<Jurisdiction[]> {
  // Single query against the bills.jurisdiction_summary view, which
  // pre-aggregates bill_count, enacted_count and last_scraped_at in SQL.
  const { data, error } = await supabase
    .from("jurisdiction_summary")
    .select("code, name, level, coverage, source_url, bill_count, enacted_count, last_scraped_at")
    .order("code");
  if (error) throw error;
  return (data ?? []).map((j) => ({
    code: j.code, name: j.name, level: j.level as "federal" | "state",
    coverage: j.coverage as Coverage, source_url: j.source_url,
    bill_count: j.bill_count ?? 0,
    enacted_count: j.enacted_count ?? 0,
    last_scraped_at: j.last_scraped_at ?? null,
  }));
}

async function coverage(): Promise<CoverageSummary> {
  const { data: js, error } = await supabase
    .from("jurisdictions")
    .select("code, name, coverage, source_url, level")
    .eq("level", "state")
    .order("name");
  if (error) throw error;
  const totals = { full: 0, stub: 0, planned: 0 };
  const states = (js ?? []).map((j) => {
    const c = j.coverage as Coverage;
    totals[c] += 1;
    return { code: j.code, name: j.name, coverage: c, source_url: j.source_url };
  });
  return { totals, states };
}

async function kindCounts(code: string): Promise<KindCounts> {
  const out = {} as KindCounts;
  // Build a fresh query per kind: supabase-js builders are mutable, so
  // sharing one and calling .eq("kind", k) seven times stacks seven
  // mutually-exclusive filters onto the same request (= zero counts).
  await Promise.all(ALL_KINDS.map(async (k) => {
    const { count } = await supabase
      .from("bills")
      .select("id", { count: "exact", head: true })
      .eq("jurisdiction", code)
      .eq("kind", k);
    out[k] = count ?? 0;
  }));
  return out;
}

// Best-effort matched summary for a page of bills, computed server-side by
// the bills.bill_list_summary view (never ships diffs over the wire). If the
// view isn't present yet, or the call fails, we degrade gracefully: the list
// still renders, just without the Corpus/RuleSpec chips. Bounded to the ids
// actually on screen so the jsonb work stays cheap.
type MatchedSummary = { matched_encodings: MatchedEncoding[]; matched_corpus: MatchedCorpus[] };

async function fetchMatchedSummary(ids: string[]): Promise<Map<string, MatchedSummary>> {
  const out = new Map<string, MatchedSummary>();
  if (ids.length === 0) return out;
  try {
    const { data, error } = await supabase
      .from("bill_list_summary")
      .select("id, matched_encodings, matched_corpus")
      .in("id", ids);
    if (error || !data) return out;
    for (const r of data as any[]) {
      const matched_corpus = ((r.matched_corpus ?? []) as MatchedCorpus[]).map((c) => ({
        ...c,
        axiom_url: c.axiom_url ?? `${AXIOM_APP_URL}/${c.citation_path}`,
      }));
      out.set(r.id, {
        matched_encodings: (r.matched_encodings ?? []) as MatchedEncoding[],
        matched_corpus,
      });
    }
  } catch {
    // Network/transient/view-missing — list renders without matched chips.
  }
  return out;
}

async function bills(
  code: string,
  opts: { status?: NormalizedStatus; kind?: BillKind[]; relevance?: Relevance } = {},
): Promise<{ bills: BillRow[]; applied_kinds: BillKind[]; applied_relevance: Relevance }> {
  // The list query stays deliberately lean: it must NOT select the heavy
  // `diffs` JSONB or embed every action. Pulling diffs for up to 500 rows
  // blew past Supabase's statement timeout on large jurisdictions (federal)
  // and returned a 500. The derived matched_* data comes from a cheap
  // server-side summary instead (see fetchMatchedSummary).
  let q = supabase
    .from("bills")
    .select(`
      id, number, title, chamber, kind, current_status, current_status_at,
      first_seen_at, source_url, session_id,
      sessions:session_id (name)
    `)
    .eq("jurisdiction", code);

  if (opts.status) q = q.eq("current_status", opts.status);
  const kinds = opts.kind && opts.kind.length ? opts.kind : ALL_KINDS;
  q = q.in("kind", kinds);
  // Relevance filters server-side on the materialized flags. Filtering
  // client-side over the 500-row window silently returned nothing when
  // the matching bills' last actions fell outside the newest 500.
  if (opts.relevance === "touches_corpus") q = q.eq("touches_corpus", true);
  if (opts.relevance === "touches_rulespec") q = q.eq("touches_rulespec", true);
  q = q.order("current_status_at", { ascending: false, nullsFirst: false });

  const { data: rows, error } = await q.limit(500);
  if (error) throw error;

  const matched = await fetchMatchedSummary((rows ?? []).map((r: any) => r.id));

  const relevance: Relevance = opts.relevance ?? "any";
  const billsOut: BillRow[] = [];
  for (const r of rows ?? []) {
    // Relevance is already filtered server-side on the materialized
    // flags; don't re-filter on the best-effort matched summary here —
    // if that fetch fails, every row would vanish.
    const m = matched.get(r.id) ?? { matched_encodings: [], matched_corpus: [] };
    billsOut.push({
      id: r.id, number: r.number, title: r.title, chamber: r.chamber,
      kind: r.kind as BillKind,
      current_status: r.current_status as NormalizedStatus,
      current_status_at: r.current_status_at,
      latest_action_at: r.current_status_at ?? null,
      first_seen_at: r.first_seen_at,
      source_url: r.source_url,
      session_name: (r as any).sessions?.name ?? "",
      matched_encodings: m.matched_encodings,
      matched_corpus: m.matched_corpus,
    });
  }
  return { bills: billsOut, applied_kinds: kinds, applied_relevance: relevance };
}

async function bill(id: string): Promise<BillDetail> {
  const { data: r, error } = await supabase
    .from("bills")
    .select(`
      *,
      sessions:session_id (name),
      jurisdictions:jurisdiction (name),
      bill_actions (occurred_at, chamber, action_text, normalized_status, source_url),
      bill_versions (label, source_url, format, fetched_at),
      bill_texts (version_label, format, text, fetched_at),
      bill_citations (citation)
    `)
    .eq("id", id)
    .maybeSingle();
  if (error) throw error;
  if (!r) throw new Error("bill not found");

  const actions: BillAction[] = (r.bill_actions ?? [])
    .sort((a: any, b: any) => a.occurred_at < b.occurred_at ? -1 : 1)
    .map((a: any) => ({
      occurred_at: a.occurred_at,
      chamber: a.chamber,
      action_text: a.action_text,
      normalized_status: a.normalized_status,
      source_url: a.source_url,
      versions: [],
    }));

  const versions: BillVersion[] = (r.bill_versions ?? []).map((v: any) => ({
    label: v.label, source_url: v.source_url, format: v.format,
    fetched_at: v.fetched_at,
  }));

  const texts = (r.bill_texts ?? []).map((t: any) => ({
    version_label: t.version_label, format: t.format,
    text: t.text, fetched_at: t.fetched_at,
  }));

  const latest_action_at = actions.length ? actions[actions.length - 1].occurred_at : null;

  const { matched_encodings, matched_corpus } = buildMatchedForBill(
    r.diffs as BillDiffs | null,
  );

  return {
    id: r.id, number: r.number, title: r.title, chamber: r.chamber,
    kind: r.kind, current_status: r.current_status,
    current_status_at: r.current_status_at,
    latest_action_at,
    first_seen_at: r.first_seen_at,
    source_url: r.source_url,
    session_name: (r as any).sessions?.name ?? "",
    jurisdiction: r.jurisdiction,
    jurisdiction_name: (r as any).jurisdictions?.name ?? r.jurisdiction,
    summary: r.summary,
    subjects: r.subjects ?? [],
    sponsors: r.sponsors ?? [],
    actions, versions, unclaimed_versions: [], texts,
    matched_encodings, matched_corpus,
  };
}

async function billVariants(id: string): Promise<RuleVariant[]> {
  const { data, error } = await supabase
    .from("rule_variants")
    .select(`
      id, file_path, tier, patched_rule_names, baseline_yaml, patched_yaml,
      diff_summary, note, effective_from, proposed_by, proposed_model,
      axiom_encodings:encoding_id (repo, citation)
    `)
    .eq("bill_id", id)
    .order("tier")
    .order("file_path");
  if (error) throw error;
  return (data ?? []).map((v: any) => ({
    id: v.id,
    file_path: v.file_path,
    tier: v.tier,
    patched_rule_names: v.patched_rule_names ?? [],
    baseline_yaml: v.baseline_yaml,
    patched_yaml: v.patched_yaml,
    diff_summary: v.diff_summary,
    note: v.note,
    effective_from: v.effective_from,
    proposed_by: v.proposed_by ?? null,
    proposed_model: v.proposed_model ?? null,
    encoding: v.axiom_encodings ? {
      repo: v.axiom_encodings.repo,
      citation: v.axiom_encodings.citation,
      github_url: `https://github.com/TheAxiomFoundation/${v.axiom_encodings.repo}/blob/main/${v.file_path}`,
    } : null,
  }));
}

async function billDiffs(id: string): Promise<BillDiffs> {
  const { data, error } = await supabase
    .from("bills")
    .select("diffs")
    .eq("id", id)
    .maybeSingle();
  if (error) throw error;
  return (data?.diffs as BillDiffs | null) ?? { sections: [] };
}

async function recent(
  status: NormalizedStatus = "enacted",
  _kind?: BillKind[],
): Promise<RecentRow[]> {
  const { data, error } = await supabase
    .from("bills")
    .select(`
      id, jurisdiction, number, title, current_status, current_status_at,
      source_url,
      jurisdictions:jurisdiction (name, level)
    `)
    .eq("current_status", status)
    .order("current_status_at", { ascending: false, nullsFirst: false })
    .limit(50);
  if (error) throw error;
  return (data ?? []).map((r: any) => ({
    id: r.id,
    jurisdiction: r.jurisdiction,
    jurisdiction_name: r.jurisdictions?.name ?? r.jurisdiction,
    jurisdiction_level: r.jurisdictions?.level ?? "state",
    number: r.number, title: r.title,
    current_status: r.current_status,
    current_status_at: r.current_status_at,
    source_url: r.source_url,
  }));
}

export const api = {
  jurisdictions,
  coverage,
  kindCounts,
  bills,
  bill,
  billDiffs,
  billVariants,
  recent,
};
