import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Jurisdiction } from "../lib/api";

export function Home() {
  const [data, setData] = useState<Jurisdiction[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.jurisdictions().then(setData).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="error">API unreachable — is uvicorn running? ({err})</p>;
  if (!data) return <p>Loading…</p>;

  const federal = data.filter((j) => j.level === "federal");
  // Only show state cards for jurisdictions we actually scrape; the rest live
  // in the coverage section as a roll-up.
  const wiredStates = data.filter(
    (j) => j.level === "state" && j.coverage !== "planned",
  );

  return (
    <div>
      <p className="page-eyebrow">§ 01 · jurisdictions</p>
      <h1>Where law happens.</h1>
      <p className="hint">
        Each jurisdiction publishes its own bill stream. The enacted count is
        the feed Axiom subscribes to when deciding whether a RuleSpec needs
        re-encoding.
      </p>

      <h2>Federal</h2>
      <div className="grid">
        {federal.map((j) => <JurisdictionCard key={j.code} j={j} />)}
      </div>

      <h2>States (active)</h2>
      <div className="grid">
        {wiredStates.map((j) => <JurisdictionCard key={j.code} j={j} />)}
      </div>

      <p className="hint" style={{ marginTop: 28 }}>
        See <Link to="/coverage">Coverage</Link> for the full state wire-up roadmap.
      </p>
    </div>
  );
}

function JurisdictionCard({ j }: { j: Jurisdiction }) {
  return (
    <Link to={`/j/${j.code}`} className={`card card--${j.coverage}`}>
      <div className="card-eyebrow">
        <span className="kicker-mark">§</span>
        <span>{j.level}</span>
        <span className={`coverage-pill coverage-pill--${j.coverage}`}>
          {j.coverage === "full" ? "live" : j.coverage}
        </span>
      </div>
      <h3>{j.name}</h3>
      <div className="card-stats">
        <span><strong>{j.bill_count.toLocaleString()}</strong> bills tracked</span>
        <span><strong>{j.enacted_count.toLocaleString()}</strong> enacted</span>
      </div>
      <code>{j.code}</code>
    </Link>
  );
}
