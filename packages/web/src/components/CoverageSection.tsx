import { useEffect, useState } from "react";
import { api, type Coverage, type CoverageSummary } from "../lib/api";

const COVERAGE_LABEL: Record<Coverage, string> = {
  full:    "Wired up",
  stub:    "Scaffolded",
  planned: "Planned",
};

const COVERAGE_DESC: Record<Coverage, string> = {
  full:    "Scraper is live, tested, and writing to the DB.",
  stub:    "File shape and status vocabulary exist; scrape() is not implemented yet.",
  planned: "On the roadmap. No scraper yet.",
};

export function CoverageSection() {
  const [data, setData] = useState<CoverageSummary | null>(null);
  useEffect(() => { api.coverage().then(setData).catch(() => setData(null)); }, []);

  if (!data) return null;

  const { totals, states } = data;
  const groups: Coverage[] = ["full", "stub", "planned"];

  return (
    <section className="coverage">
      <p className="page-eyebrow">§ coverage</p>
      <h2 className="coverage-h">State wire-up</h2>
      <p className="hint">
        Which state legislatures are actually feeding the Pipeline B trigger.
        Federal is tracked separately above.
      </p>

      <div className="coverage-totals">
        {groups.map((g) => (
          <div key={g} className={`coverage-total coverage-total--${g}`}>
            <div className="coverage-total-n">{totals[g]}</div>
            <div className="coverage-total-label">{COVERAGE_LABEL[g]}</div>
            <div className="coverage-total-desc">{COVERAGE_DESC[g]}</div>
          </div>
        ))}
      </div>

      <div className="coverage-states">
        {groups.map((g) => {
          const list = states.filter((s) => s.coverage === g);
          if (list.length === 0) return null;
          return (
            <div key={g} className="coverage-group">
              <h3 className={`coverage-group-h coverage-group-h--${g}`}>
                {COVERAGE_LABEL[g]}
                <span className="coverage-group-count">{list.length}</span>
              </h3>
              <ul className={`coverage-list coverage-list--${g}`}>
                {list.map((s) => (
                  <li key={s.code} className="coverage-state">
                    <span className="coverage-state-code">{s.code.replace("us-", "").toUpperCase()}</span>
                    <span className="coverage-state-name">{s.name}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
