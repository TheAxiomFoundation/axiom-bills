import { useEffect, useState } from "react";
import { api, type AffectedRules as TRules } from "../lib/api";

export function AffectedRules({ billId }: { billId: string }) {
  const [data, setData] = useState<TRules | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.affectedRules(billId).then(setData).catch(() => setErr(true));
  }, [billId]);

  if (err) return null;
  if (!data) return null;
  if (data.totals.in_scope === 0) return null;

  return (
    <section className="affected-rules">
      <h3>Pipeline B trigger</h3>
      <p className="hint">
        Per <a href="https://github.com/TheAxiomFoundation/axiom-architecture/blob/main/docs/corpus-encoding-mapping.md" target="_blank" rel="noreferrer">
        corpus-encoding-mapping
        </a>, rules whose proof-atom text the bill strikes verbatim are
        the rules whose grounding has demonstrably changed. Those need
        re-encoding on enactment. Other in-scope rules may need
        re-validation but are lower priority.
      </p>

      <div className="rules-totals">
        <div className={`rules-total rules-total--hits ${data.totals.atom_hits > 0 ? "active" : ""}`}>
          <div className="rules-total-n">{data.totals.atom_hits}</div>
          <div className="rules-total-label">Atom hits</div>
          <div className="rules-total-desc">Re-encode</div>
        </div>
        <div className={`rules-total rules-total--scope ${data.totals.in_scope - data.totals.atom_hits > 0 ? "active" : ""}`}>
          <div className="rules-total-n">{data.totals.in_scope - data.totals.atom_hits}</div>
          <div className="rules-total-label">In scope</div>
          <div className="rules-total-desc">Re-validate</div>
        </div>
      </div>

      {data.atom_hits.length > 0 && (
        <>
          <p className="encodings-kicker">Atom hits · would re-encode</p>
          <ul className="rules-list">
            {data.atom_hits.map((r) => (
              <li key={`${r.repo}-${r.file_path}-${r.rule_name}`}
                  className="rule-row rule-row--hit">
                <header className="rule-header">
                  <code className="rule-name">{r.rule_name}</code>
                  <span className="rule-source">{r.rule_source}</span>
                  <a href={r.github_url} target="_blank" rel="noreferrer"
                     className="rule-file">
                    {r.file_path}
                  </a>
                </header>
                <ul className="rule-matches">
                  {r.matches.map((m, i) => (
                    <li key={i} className="rule-match">
                      <span className="rule-match-label">strike</span>
                      <q>{m.strike_text}</q>
                      <span className="rule-match-label">found in</span>
                      <span className="rule-match-where">
                        {m.atom_kind || "atom"} · {m.bill_citation}
                      </span>
                      <p className="rule-atom-text">{m.atom_text}</p>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}

      {data.scope_only.length > 0 && (
        <>
          <p className="encodings-kicker">In scope · would re-validate</p>
          <ul className="rules-list rules-list--scope">
            {data.scope_only.map((r) => (
              <li key={r.id} className="rule-row rule-row--scope">
                <code className="rule-name">{r.rule_name}</code>
                <span className="rule-source">{r.rule_source}</span>
                <a href={r.github_url} target="_blank" rel="noreferrer"
                   className="rule-file">
                  {r.file_path}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
