import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type BillRow, type NormalizedStatus } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate, STATUS_LABEL } from "../lib/format";

const FILTERABLE: NormalizedStatus[] = [
  "introduced", "in_committee", "passed_chamber",
  "passed_both", "enrolled", "signed", "enacted", "vetoed",
];

export function JurisdictionPage() {
  const { code = "" } = useParams();
  const [bills, setBills] = useState<BillRow[] | null>(null);
  const [filter, setFilter] = useState<NormalizedStatus | "">("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setBills(null);
    api.bills(code, filter || undefined)
      .then((r) => setBills(r.bills))
      .catch((e) => setErr(String(e)));
  }, [code, filter]);

  return (
    <div>
      <p className="crumb"><Link to="/">← all jurisdictions</Link></p>
      <h1>{code}</h1>

      <div className="filters">
        <button
          className={filter === "" ? "on" : ""}
          onClick={() => setFilter("")}
        >
          All
        </button>
        {FILTERABLE.map((s) => (
          <button
            key={s}
            className={filter === s ? "on" : ""}
            onClick={() => setFilter(s)}
          >
            {STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      {err && <p className="error">{err}</p>}
      {!bills ? <p>Loading…</p> : (
        bills.length === 0 ? (
          <p className="hint">No bills match. If counts are zero everywhere, run the scraper first:
            <br/><code>axiom-bills scrape --jurisdiction {code} --limit 50</code></p>
        ) : (
          <table className="bills">
            <thead>
              <tr>
                <th>Number</th>
                <th>Title</th>
                <th>Status</th>
                <th>Last action</th>
              </tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr key={b.id}>
                  <td>
                    <Link to={`/bills/${b.id}`}>{b.number}</Link>
                  </td>
                  <td className="title-cell">{b.title || <em>untitled</em>}</td>
                  <td><StatusBadge status={b.current_status} /></td>
                  <td>{fmtDate(b.current_status_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  );
}
