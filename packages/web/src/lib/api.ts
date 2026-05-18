export type Jurisdiction = {
  code: string;
  name: string;
  level: "federal" | "state";
  source_url: string;
  bill_count: number;
  enacted_count: number;
};

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

export type BillRow = {
  id: string;
  number: string;
  title: string | null;
  chamber: string;
  current_status: NormalizedStatus;
  current_status_at: string | null;
  first_seen_at: string;
  source_url: string;
  session_name: string;
};

export type BillAction = {
  occurred_at: string;
  chamber: string | null;
  action_text: string;
  normalized_status: NormalizedStatus | null;
  source_url: string | null;
};

export type BillVersion = {
  label: string;
  source_url: string;
  format: string;
  fetched_at: string | null;
};

export type BillDetail = BillRow & {
  jurisdiction: string;
  jurisdiction_name: string;
  summary: string | null;
  subjects: string[];
  sponsors: { name: string; role?: string; party?: string; district?: string }[];
  actions: BillAction[];
  versions: BillVersion[];
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

export const api = {
  jurisdictions: () => get<Jurisdiction[]>("/jurisdictions"),
  bills: (code: string, status?: NormalizedStatus) =>
    get<{ bills: BillRow[] }>(
      `/jurisdictions/${code}/bills${status ? `?status=${status}` : ""}`,
    ),
  bill: (id: string) => get<BillDetail>(`/bills/${id}`),
  recent: (status: NormalizedStatus = "enacted") =>
    get<RecentRow[]>(`/recent?status=${status}`),
};
