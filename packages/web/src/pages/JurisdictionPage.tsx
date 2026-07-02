import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ALL_KINDS,
  api,
  type BillKind,
  type BillRow,
  type KindCounts,
  type NormalizedStatus,
  type Relevance,
} from "../lib/api";
import { KindFilter } from "../components/KindFilter";
import { RelevanceFilter } from "../components/RelevanceFilter";
import { StatusBadge } from "../components/StatusBadge";
import { StatusFilter } from "../components/StatusFilter";
import { fmtDate, KIND_LABEL } from "../lib/format";
import { errorMessage } from "../lib/errors";
import { retry } from "../lib/retry";

function EmptyState({ code, counts, filtered, relevance, onClear }: {
  code: string;
  counts: KindCounts | undefined;
  filtered: boolean;
  relevance: Relevance;
  onClear: () => void;
}) {
  const total = counts
    ? Object.values(counts).reduce((a, b) => a + b, 0)
    : null;

  // The jurisdiction genuinely has no bills yet (e.g. its scraper needs
  // an API key that isn't configured).
  if (total === 0) {
    return (
      <p className="hint">
        No bills have been ingested for <code>{code}</code> yet — the
        scraper for this jurisdiction hasn't run (some sources need an
        API key). To pull bills locally:
        <br /><code>axiom-bills scrape --jurisdiction {code} --limit 50</code>
      </p>
    );
  }

  // Bills exist; the current filters just exclude all of them.
  return (
    <p className="hint">
      No bills match the current filters
      {relevance !== "any" && code !== "us" && (
        <> — note that Corpus/RuleSpec matching currently covers federal
        bills only, so “{
          relevance === "touches_corpus" ? "Touches corpus"
          : relevance === "needs_new_encoding" ? "Needs new encoding"
          : "Touches RuleSpec"
        }” is always empty for states</>
      )}
      .{" "}
      {filtered && (
        <button className="link-button" onClick={onClear}>
          Reset filters
        </button>
      )}
    </p>
  );
}

export function JurisdictionPage() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const [bills, setBills] = useState<BillRow[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [counts, setCounts] = useState<KindCounts | undefined>();
  const [statusFilter, setStatusFilter] = useState<NormalizedStatus | "">("");
  const [kinds, setKinds] = useState<BillKind[]>(["substantive"]);
  const [relevance, setRelevance] = useState<Relevance>("any");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    retry(() => api.kindCounts(code)).then(setCounts).catch(() => setCounts(undefined));
  }, [code]);

  useEffect(() => {
    setBills(null);
    setHasMore(false);
    setErr(null);
    retry(() => api.bills(code, {
      status: statusFilter || undefined,
      kind: kinds,
      relevance,
    }))
      .then((r) => { setBills(r.bills); setHasMore(r.has_more); })
      .catch((e) => setErr(errorMessage(e)));
  }, [code, statusFilter, kinds, relevance]);

  const loadMore = () => {
    if (!bills || loadingMore) return;
    setLoadingMore(true);
    retry(() => api.bills(code, {
      status: statusFilter || undefined,
      kind: kinds,
      relevance,
      offset: bills.length,
    }))
      .then((r) => {
        setBills([...bills, ...r.bills]);
        setHasMore(r.has_more);
      })
      .catch((e) => setErr(errorMessage(e)))
      .finally(() => setLoadingMore(false));
  };

  return (
    <div>
      <p className="crumb"><Link to="/">← Jurisdictions</Link></p>
      <p className="page-eyebrow">§ {code}</p>
      <h1>Bill stream</h1>

      <div className="filter-bar">
        <KindFilter selected={kinds} onChange={setKinds} counts={counts} />
        <StatusFilter value={statusFilter} onChange={setStatusFilter} />
        <RelevanceFilter value={relevance} onChange={setRelevance} />
      </div>

      {err && <p className="error">{err}</p>}
      {!bills ? <p>Loading…</p> : (
        bills.length === 0 ? (
          <EmptyState
            code={code}
            counts={counts}
            filtered={kinds.length < 7 || !!statusFilter || relevance !== "any"}
            relevance={relevance}
            onClear={() => {
              setKinds([...ALL_KINDS]);
              setStatusFilter("");
              setRelevance("any");
            }}
          />
        ) : (
          <div className="table-scroll">
          <table className="bills">
            <thead>
              <tr>
                <th>Number</th>
                <th>Title</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Corpus</th>
                <th>RuleSpec</th>
                <th>Last action</th>
              </tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr
                  key={b.id}
                  className="bill-row"
                  tabIndex={0}
                  role="link"
                  onClick={() => navigate(`/bills/${b.id}`)}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      navigate(`/bills/${b.id}`);
                    }
                  }}
                >
                  <td>
                    {/* Keep an inline Link so middle-click / cmd-click /
                        right-click → open-in-new-tab keep working, and
                        screen readers still announce the bill number as
                        a link. */}
                    <Link to={`/bills/${b.id}`} onClick={(ev) => ev.stopPropagation()}>
                      {b.number}
                    </Link>
                  </td>
                  <td className="title-cell">{b.title || <em>untitled</em>}</td>
                  <td>
                    <span className={`kind-chip kind-chip--${b.kind}`}>
                      {KIND_LABEL[b.kind]}
                    </span>
                  </td>
                  <td><StatusBadge status={b.current_status} /></td>
                  <td className="encodings-cell">
                    {b.matched_corpus.length === 0 ? (
                      <span className="encodings-empty">—</span>
                    ) : (
                      <ul className="encodings-inline">
                        {b.matched_corpus.slice(0, 3).map((c) => (
                          <li key={c.citation_path}>
                            <a href={c.axiom_url} target="_blank"
                               rel="noreferrer" title={c.heading || c.citation}
                               onClick={(ev) => ev.stopPropagation()}>
                              {c.citation}
                            </a>
                          </li>
                        ))}
                        {b.matched_corpus.length > 3 && (
                          <li className="encodings-more">
                            +{b.matched_corpus.length - 3}
                          </li>
                        )}
                      </ul>
                    )}
                  </td>
                  <td className="encodings-cell">
                    {b.matched_encodings.length === 0 ? (
                      <span className="encodings-empty">—</span>
                    ) : (
                      <ul className="encodings-inline">
                        {b.matched_encodings.slice(0, 3).map((e) => (
                          <li key={e.file_path}>
                            <a href={e.github_url} target="_blank"
                               rel="noreferrer" title={e.file_path}
                               onClick={(ev) => ev.stopPropagation()}>
                              {e.file_path.replace(/^statutes\//, "")
                                          .replace(/^regulations\//, "")
                                          .replace(/\.yaml$/, "")}
                            </a>
                          </li>
                        ))}
                        {b.matched_encodings.length > 3 && (
                          <li className="encodings-more">
                            +{b.matched_encodings.length - 3}
                          </li>
                        )}
                      </ul>
                    )}
                  </td>
                  <td>{fmtDate(b.latest_action_at ?? b.first_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && (
            <p className="load-more">
              <button className="link-button" onClick={loadMore}
                      disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load older bills"}
              </button>
            </p>
          )}
          </div>
        )
      )}
    </div>
  );
}
