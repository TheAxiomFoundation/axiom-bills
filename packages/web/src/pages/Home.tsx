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
  const states = data.filter((j) => j.level === "state");

  return (
    <div>
      <h1>Jurisdictions</h1>
      <p className="hint">
        Click a jurisdiction to see its bill list. The “enacted” count is the
        feed that triggers Axiom’s encoding pipeline.
      </p>

      <h2>Federal</h2>
      <div className="grid">
        {federal.map((j) => <JurisdictionCard key={j.code} j={j} />)}
      </div>

      <h2>States</h2>
      <div className="grid">
        {states.map((j) => <JurisdictionCard key={j.code} j={j} />)}
      </div>
    </div>
  );
}

function JurisdictionCard({ j }: { j: Jurisdiction }) {
  return (
    <Link to={`/j/${j.code}`} className="card">
      <h3>{j.name}</h3>
      <div className="card-stats">
        <span><strong>{j.bill_count.toLocaleString()}</strong> bills tracked</span>
        <span><strong>{j.enacted_count.toLocaleString()}</strong> enacted</span>
      </div>
      <code>{j.code}</code>
    </Link>
  );
}
