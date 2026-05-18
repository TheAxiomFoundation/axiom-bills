import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type BillDetail } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate } from "../lib/format";

export function BillPage() {
  const { billId = "" } = useParams();
  const [bill, setBill] = useState<BillDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.bill(billId).then(setBill).catch((e) => setErr(String(e)));
  }, [billId]);

  if (err) return <p className="error">{err}</p>;
  if (!bill) return <p>Loading…</p>;

  return (
    <div>
      <p className="crumb">
        <Link to="/">all jurisdictions</Link>
        {" · "}
        <Link to={`/j/${bill.jurisdiction}`}>{bill.jurisdiction_name}</Link>
      </p>

      <header className="bill-header">
        <h1>{bill.number}</h1>
        <StatusBadge status={bill.current_status} />
        <a href={bill.source_url} target="_blank" rel="noreferrer">source ↗</a>
      </header>

      <h2 className="bill-title">{bill.title || <em>untitled</em>}</h2>
      <p className="session">
        {bill.session_name} · chamber: {bill.chamber}
      </p>

      {bill.summary && (
        <section>
          <h3>Summary</h3>
          <p className="summary">{bill.summary}</p>
        </section>
      )}

      {bill.subjects?.length ? (
        <section>
          <h3>Subjects</h3>
          <div className="chips">
            {bill.subjects.map((s) => <span key={s} className="chip">{s}</span>)}
          </div>
        </section>
      ) : null}

      {bill.sponsors?.length ? (
        <section>
          <h3>Sponsors</h3>
          <ul className="sponsors">
            {bill.sponsors.map((s, i) => (
              <li key={i}>
                {s.name} {s.role && <em>({s.role})</em>}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h3>Actions</h3>
        <ol className="timeline">
          {bill.actions.map((a, i) => (
            <li key={i}>
              <time>{fmtDate(a.occurred_at)}</time>
              <div>
                <p>{a.action_text}</p>
                {a.normalized_status && a.normalized_status !== "unknown" && (
                  <StatusBadge status={a.normalized_status} />
                )}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {bill.versions.length ? (
        <section>
          <h3>Versions</h3>
          <ul>
            {bill.versions.map((v) => (
              <li key={v.label}>
                <a href={v.source_url} target="_blank" rel="noreferrer">
                  {v.label}
                </a>{" "}
                <code>{v.format}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
