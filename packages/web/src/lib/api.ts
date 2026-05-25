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
  | "substantive"
  | "placeholder"
  | "ceremonial"
  | "appropriations"
  | "procedural"
  | "vehicle"
  | "unknown";

export const ALL_KINDS: BillKind[] = [
  "substantive", "placeholder", "ceremonial",
  "appropriations", "procedural", "vehicle", "unknown",
];

export type Relevance = "any" | "touches_corpus" | "touches_rulespec";

export type NormalizedStatus =
  | "introduced"
  | "in_committee"
  | "passed_chamber"
  | "passed_both"
  | "enrolled"
  | "signed"
  | "enacted"
  | "vetoed"
  | "veto_overridden"
  | "failed"
  | "unknown";

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

export type BillVersionFormat = {
  format: string;
  source_url: string;
  label: string;
};

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
  texts: {
    version_label: string;
    format: string;
    text: string;
    fetched_at: string;
  }[];
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

export type AffectedEncodings = {
  matched: (ExtractedCitation & { encodings: AxiomEncoding[] })[];
  unmatched: ExtractedCitation[];
  citations: ExtractedCitation[];
};

export type DiffBlock = {
  kind: "equal" | "add" | "remove";
  text: string;
};

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

export type BillDiffs = {
  sections: BillDiffSection[];
};

export type AffectedRuleAtomMatch = {
  bill_citation: string;
  strike_text: string;
  atom_path: string | null;
  atom_kind: string | null;
  atom_text: string;
};

export type AffectedRule = {
  rule_name: string;
  rule_source: string;
  repo: string;
  file_path: string;
  encoding_citation: string;
  github_url: string;
  matches: AffectedRuleAtomMatch[];
};

export type ScopeOnlyRule = {
  id: string;
  rule_name: string;
  rule_source: string;
  repo: string;
  file_path: string;
  encoding_citation: string;
  github_url: string;
};

export type AffectedRules = {
  atom_hits: AffectedRule[];
  scope_only: ScopeOnlyRule[];
  totals: { in_scope: number; atom_hits: number };
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

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function withParams(path: string, params: Record<string, string | string[] | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null) continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x));
    else u.append(k, v);
  }
  const qs = u.toString();
  return qs ? `${path}?${qs}` : path;
}

export const api = {
  jurisdictions: () => get<Jurisdiction[]>("/jurisdictions"),
  coverage: () => get<CoverageSummary>("/coverage"),
  bills: (
    code: string,
    opts: { status?: NormalizedStatus; kind?: BillKind[]; relevance?: Relevance } = {},
  ) =>
    get<{ bills: BillRow[]; applied_kinds: BillKind[]; applied_relevance: Relevance }>(
      withParams(`/jurisdictions/${code}/bills`, {
        status: opts.status,
        kind: opts.kind,
        relevance: opts.relevance,
      }),
    ),
  kindCounts: (code: string) => get<KindCounts>(`/jurisdictions/${code}/kinds`),
  bill: (id: string) => get<BillDetail>(`/bills/${id}`),
  affectedEncodings: (id: string) =>
    get<AffectedEncodings>(`/bills/${id}/affected-encodings`),
  billDiffs: (id: string) => get<BillDiffs>(`/bills/${id}/diffs`),
  affectedRules: (id: string) => get<AffectedRules>(`/bills/${id}/affected-rules`),
  recent: (status: NormalizedStatus = "enacted", kind?: BillKind[]) =>
    get<RecentRow[]>(withParams("/recent", { status, kind })),
};
