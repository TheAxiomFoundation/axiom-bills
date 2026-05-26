import { useEffect, useState } from "react";
import { api, type RuleVariant, type VariantTier } from "../lib/api";

const TIER_LABEL: Record<VariantTier, string> = {
  substitution: "auto-patched",
  list:         "needs review · list",
  structural:   "needs review · structural",
  no_op:        "no-op",
};

const TIER_DESC: Record<VariantTier, string> = {
  substitution:
    "Scalar substitution — atom text + formula version appended. Run microsim with this variant to A/B against current law.",
  list:
    "Bill adds a list item (new exception, new category). Mechanical YAML insert but needs a human to author the rule branch.",
  structural:
    "Bill rewrites the section (amend-to-read / repeal / redesignate). Needs human or LLM-assisted re-encoding.",
  no_op:
    "Bill touches this section but no atom of any rule matched the bill's needle. Baseline unchanged.",
};

export function BillVariants({ billId }: { billId: string }) {
  const [variants, setVariants] = useState<RuleVariant[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.billVariants(billId).then(setVariants).catch(() => setErr(true));
  }, [billId]);

  if (err || !variants) return null;
  if (variants.length === 0) return null;

  const grouped: Record<VariantTier, RuleVariant[]> = {
    substitution: [], list: [], structural: [], no_op: [],
  };
  for (const v of variants) grouped[v.tier].push(v);

  return (
    <section className="variants">
      <h3>Pipeline B variants</h3>
      <p className="hint">
        Proposed re-encodings of rulespec rules whose grounding this bill
        would change. Auto-patched variants append a new version row
        keyed to the bill's effective date — the baseline is preserved
        so historical computation still works.
      </p>

      {(["substitution", "list", "structural", "no_op"] as VariantTier[])
        .filter((t) => grouped[t].length > 0)
        .map((tier) => (
          <div key={tier} className="variant-group">
            <header className="variant-group-header">
              <span className={`tier-pill tier-pill--${tier}`}>
                {TIER_LABEL[tier]}
              </span>
              <span className="variant-group-desc">{TIER_DESC[tier]}</span>
            </header>
            <ul className="variant-list">
              {grouped[tier].map((v) => <VariantRow key={v.id} v={v} />)}
            </ul>
          </div>
        ))}
    </section>
  );
}

function VariantRow({ v }: { v: RuleVariant }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="variant-row">
      <header className="variant-row-header">
        <code className="variant-file">{v.file_path}</code>
        {v.encoding && (
          <a href={v.encoding.github_url} target="_blank" rel="noreferrer"
             className="variant-encoding-link">
            {v.encoding.citation} ↗
          </a>
        )}
        {v.patched_rule_names.length > 0 && (
          <span className="variant-rules">
            {v.patched_rule_names.join(", ")}
          </span>
        )}
        {v.effective_from && (
          <time className="variant-effective">eff. {v.effective_from}</time>
        )}
      </header>
      {v.diff_summary && (
        <p className="variant-diff-summary">{v.diff_summary}</p>
      )}
      {v.note && <p className="variant-note">{v.note}</p>}
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
