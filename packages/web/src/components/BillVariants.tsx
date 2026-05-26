import { useEffect, useState } from "react";
import { api, type RuleVariant, type VariantTier } from "../lib/api";

const TIER_LABEL: Record<VariantTier, string> = {
  substitution: "auto-patched",
  list:         "list change",
  structural:   "structural",
  no_op:        "no-op",
};

const TIER_SHORT: Record<VariantTier, string> = {
  substitution: "atom + formula version appended; ready to A/B",
  list:         "needs human authoring of a new rule branch",
  structural:   "needs human or LLM-assisted re-encoding",
  no_op:        "no atom matched — baseline unchanged",
};

export function BillVariants({ billId }: { billId: string }) {
  const [variants, setVariants] = useState<RuleVariant[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.billVariants(billId).then(setVariants).catch(() => setErr(true));
  }, [billId]);

  if (err || !variants || variants.length === 0) return null;

  const grouped: Record<VariantTier, RuleVariant[]> = {
    substitution: [], list: [], structural: [], no_op: [],
  };
  for (const v of variants) grouped[v.tier].push(v);

  return (
    <section className="variants">
      <header className="variants-header">
        <h3>Pipeline B variants</h3>
        <p className="variants-tagline">
          Rulespec rules whose grounding this bill would change.
        </p>
      </header>

      {(["substitution", "list", "structural", "no_op"] as VariantTier[])
        .filter((t) => grouped[t].length > 0)
        .map((tier) => (
          <div key={tier} className="variant-group">
            <div className="variant-group-header">
              <span className={`tier-pill tier-pill--${tier}`}>
                {TIER_LABEL[tier]}
              </span>
              <span className="variant-group-count">
                {grouped[tier].length}
              </span>
              <span className="variant-group-desc">{TIER_SHORT[tier]}</span>
            </div>
            <ul className="variant-list">
              {grouped[tier].map((v) => <VariantRow key={v.id} v={v} />)}
            </ul>
          </div>
        ))}
    </section>
  );
}

/** Replace runs of whitespace with single spaces. */
function clean(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/** Parse the reencoder's "needle=... payload=..." note into structured halves. */
function parseScalarNote(note: string): { kind: string; needle: string; payload: string } | null {
  const m = note.match(
    /^Op (\S+) needle\/payload not a recognized scalar \(needle=(['"])(.*?)\2, payload=(['"])(.*?)\4\)\.?$/s,
  );
  if (!m) return null;
  return { kind: m[1], needle: m[3], payload: m[5] };
}

function VariantRow({ v }: { v: RuleVariant }) {
  const [open, setOpen] = useState(false);
  const parsed = v.note ? parseScalarNote(v.note) : null;

  return (
    <li className="variant-row">
      <div className="variant-row-top">
        <code className="variant-file">{v.file_path}</code>
        {v.encoding && (
          <a href={v.encoding.github_url} target="_blank" rel="noreferrer"
             className="variant-encoding-link">
            {v.encoding.citation}&nbsp;↗
          </a>
        )}
        {v.effective_from && (
          <time className="variant-effective">eff. {v.effective_from}</time>
        )}
      </div>
      {v.patched_rule_names.length > 0 && (
        <p className="variant-rules">
          rules · {v.patched_rule_names.join(" · ")}
        </p>
      )}
      {parsed ? (
        <BeforeAfterBlock
          kind={parsed.kind}
          before={parsed.needle}
          after={parsed.payload}
        />
      ) : v.note ? (
        <p className="variant-note">{clean(v.note)}</p>
      ) : null}
      {v.diff_summary && !parsed && (
        <p className="variant-diff-summary">{v.diff_summary}</p>
      )}
      {v.baseline_yaml && v.patched_yaml && (
        <>
          <button className="variant-toggle"
                  onClick={() => setOpen((x) => !x)}>
            {open ? "hide YAML diff" : "show YAML diff"}
          </button>
          {open && <YamlDiff before={v.baseline_yaml} after={v.patched_yaml} />}
        </>
      )}
    </li>
  );
}

function BeforeAfterBlock({ kind, before, after }: {
  kind: string; before: string; after: string;
}) {
  return (
    <div className="ba">
      <div className="ba-kind">{kind}</div>
      <div className="ba-pair">
        <div className="ba-side ba-side--before">
          <span className="ba-label">strike</span>
          <pre>{clean(before)}</pre>
        </div>
        <div className="ba-side ba-side--after">
          <span className="ba-label">insert</span>
          <pre>{after.trim() ? clean(after) : <em>(removed)</em>}</pre>
        </div>
      </div>
    </div>
  );
}

function YamlDiff({ before, after }: { before: string; after: string }) {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const beforeSet = new Set(beforeLines);
  const afterSet = new Set(afterLines);
  return (
    <div className="yaml-diff">
      <div className="yaml-diff-col">
        <h5>baseline</h5>
        <pre>
          {beforeLines.map((line, i) => (
            <div key={i} className={afterSet.has(line) ? "" : "removed"}>
              {line}
            </div>
          ))}
        </pre>
      </div>
      <div className="yaml-diff-col">
        <h5>variant</h5>
        <pre>
          {afterLines.map((line, i) => (
            <div key={i} className={beforeSet.has(line) ? "" : "added"}>
              {line}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
