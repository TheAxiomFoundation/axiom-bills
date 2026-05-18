import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type NormalizedStatus, type RecentRow } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate } from "../lib/format";

const STREAMS: { label: string; status: NormalizedStatus }[] = [
  { label: "Enacted",  status: "enacted" },
  { label: "Signed",   status: "signed" },
  { label: "Enrolled", status: "enrolled" },
  { label: "Vetoed",   status: "vetoed" },
];

export function RecentPage() {
  const [stream, setStream] = useState<NormalizedStatus>("enacted");
  const [rows, setRows] = useState<RecentRow[] | null>(null);

  useEffect(() => {
    setRows(null);
    api.recent(stream).then(setRows).catch(() => setRows([]));
  }, [stream]);

  return (
    <div>
      <h1>Cross-jurisdiction feed</h1>
      <p className="hint">
        This is the feed Pipeline B of the auto-update layer subscribes to.
        “Enacted” is the canonical trigger; “signed” is the next-best
        leading indicator.
      </p>

      <div className="filters">
        {STREAMS.map((s) => (
          <button
            key={s.status}
            className={stream === s.status ? "on" : ""}
            onClick={() => setStream(s.status)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {!rows ? <p>Loading…</p> : rows.length === 0 ? (
        <p className="hint">Nothing to show yet — run a scraper.</p>
      ) : (
        <ul className="recent-list">
          {rows.map((r) => (
            <li key={r.id}>
              <time>{fmtDate(r.current_status_at)}</time>
              <Link to={`/bills/${r.id}`} className="recent-number">
                <strong>{r.jurisdiction.toUpperCase()}</strong> {r.number}
              </Link>
              <span className="recent-title">{r.title || <em>untitled</em>}</span>
              <StatusBadge status={r.current_status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
