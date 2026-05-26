import { useEffect, useState } from "react";
import { api, type BillDiffSection, type BillDiffs as TDiffs, type RuleVariant } from "../lib/api";

export function BillDiffs({ billId }: { billId: string }) {
  const [data, setData] = useState<TDiffs | null>(null);
  const [variants, setVariants] = useState<RuleVariant[]>([]);
  const [active, setActive] = useState(0);
  const [err, setErr] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    api.billDiffs(billId).then(setData).catch(() => setErr(true));
    api.billVariants(billId).then(setVariants).catch(() => { /* variants are optional */ });
  }, [billId]);

  if (err) return null;
  if (!data) return <p className="hint">Computing diffs…</p>;
  if (data.sections.length === 0) return null;

  // Tabs only for sections where we have *something* to show.
  const candidates = data.sections.filter((s) => s.in_corpus || s.encoding);
  // Heuristic: a "touched" section has amendment language we detected
  // (applied or unapplied ops) OR an encoding match. A pure citation
  // with neither is just a reference — most multi-statute bills hit
  // dozens of references, and surfacing each as a tab buries the real
  // edits. Default to amended-only; offer a toggle to see all.
  const touched = candidates.filter(
    (s) => s.applied_ops.length > 0
        || s.unapplied_ops.length > 0
        || s.encoding != null,
  );
  const referenceOnly = candidates.length - touched.length;
  const visible = showAll ? candidates : (touched.length > 0 ? touched : candidates);

  if (visible.length === 0) {
    return (
      <section>
        <h3>Section-by-section change</h3>
        <p className="hint">
          None of this bill’s cited sections are in axiom-corpus or
          rulespec-us yet, so there’s nothing to diff or encode.
        </p>
      </section>
    );
  }

  const activeIdx = Math.min(active, visible.length - 1);
  const section = visible[activeIdx];

  return (
    <section className="diffs">
      <h3>Section-by-section change</h3>
      <p className="hint">
        Diff is computed by parsing the bill’s amendment instructions and
        applying them to current law from <code>axiom-corpus</code>. When
        the parser can’t auto-apply an instruction, you’ll see it in the
        unapplied list and the bill text remains the source of truth.
      </p>

      {referenceOnly > 0 && (
        <p className="diffs-toggle">
          {showAll ? (
            <>
              Showing all {candidates.length} cited sections including
              cross-references.{" "}
              <button onClick={() => setShowAll(false)}>
                Show only amended ({touched.length})
              </button>
            </>
          ) : (
            <>
              Showing {touched.length} amended/encoded sections.{" "}
              <button onClick={() => setShowAll(true)}>
                Show all {candidates.length} cited sections
                ({referenceOnly} references)
              </button>
            </>
          )}
        </p>
      )}

      <nav className="diff-tabs" role="tablist">
        {visible.map((s, i) => (
          <button
            key={s.citation}
            role="tab"
            aria-selected={i === activeIdx}
            className={`diff-tab ${i === activeIdx ? "on" : ""}`}
            onClick={() => setActive(i)}
          >
            <span className="diff-tab-cite">{s.citation}</span>
            {s.heading && <span className="diff-tab-heading">{s.heading}</span>}
            <span className={`diff-tab-status diff-tab-status--${
              s.applied_ops.length > 0 ? "applied"
                : s.unapplied_ops.length > 0 ? "unapplied"
                : !s.in_corpus ? "noop"
                : "noop"
            }`}>
              {s.applied_ops.length > 0
                ? `${s.applied_ops.length} edit${s.applied_ops.length === 1 ? "" : "s"}`
                : s.unapplied_ops.length > 0
                ? "unparsed"
                : !s.in_corpus
                ? "no corpus text"
                : "no diff detected"}
            </span>
          </button>
        ))}
      </nav>

      <SectionView section={section} variants={variants} />
    </section>
  );
}

function SectionView({ section, variants }: {
  section: BillDiffSection;
  variants: RuleVariant[];
}) {
  const hasDiff = section.diff.length > 0 && section.applied_ops.length > 0;

  return (
    <div className="diff-section">
      <div className="diff-layout">
        <div className="diff-main">
          {section.axiom_url && (
            <p className="diff-section-source">
              <a href={section.axiom_url} target="_blank" rel="noreferrer">
                View current law on Axiom ↗
              </a>
            </p>
          )}

          {hasDiff ? (
            <DiffView blocks={section.diff} />
          ) : section.in_corpus ? (
            <div className="diff-fallback">
              {section.exact_corpus_match && (
                <p className="hint">
                  {section.unapplied_ops.length > 0
                    ? "We detected amendment language but couldn’t auto-apply it. The current law text is shown below; raw instructions are in the drawer."
                    : "No amendment language detected for this section in the bill text. The current law text is shown for context."}
                </p>
              )}
              <pre className="diff-current">{section.current_text}</pre>
            </div>
          ) : (
            <div className="diff-fallback">
              <p className="hint">
                axiom-corpus doesn’t have this provision at the cited
                granularity, so there’s no current-law text to diff against.
                The RuleSpec encoding on the right is what would be re-run
                on enactment.
              </p>
            </div>
          )}

          {(section.applied_ops.length > 0 || section.unapplied_ops.length > 0) && (
            <details className="diff-ops">
              <summary>
                Parsed amendment instructions
                <span className="diff-ops-count">
                  ({section.applied_ops.length} applied,{" "}
                  {section.unapplied_ops.length} unparsed)
                </span>
              </summary>
              <ul className="diff-ops-list">
                {section.applied_ops.map((op, i) => (
                  <li key={`a${i}`} className="diff-op diff-op--applied">
                    <code className="diff-op-kind">{op.kind}</code>
                    {op.needle && (
                      <span><em>strike</em> <q>{op.needle}</q></span>
                    )}
                    {op.payload && (
                      <span><em>{op.kind === "add-end" ? "append" : "insert"}</em> <q>{op.payload.slice(0, 200)}</q></span>
                    )}
                  </li>
                ))}
                {section.unapplied_ops.map((op, i) => (
                  <li key={`u${i}`} className="diff-op diff-op--unapplied">
                    <code className="diff-op-kind">{op.kind}</code>
                    <span className="diff-op-raw">{op.raw.slice(0, 240)}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <aside className="diff-rail">
          <RuleSpecPanel section={section} variants={variants} />
        </aside>
      </div>
    </div>
  );
}

function RuleSpecPanel({ section, variants }: {
  section: BillDiffSection;
  variants: RuleVariant[];
}) {
  const enc = section.encoding;
  if (!enc) {
    return (
      <div className="rulespec-panel rulespec-panel--missing">
        <p className="rulespec-eyebrow">RuleSpec encoding</p>
        <p className="rulespec-missing">
          Not encoded in <code>rulespec-us</code> yet.
        </p>
        <p className="rulespec-hint">
          If this bill is enacted, this section will be added to the
          encoder backlog rather than auto-re-encoded.
        </p>
      </div>
    );
  }

  // Match the bill's variant for this exact encoded file. If one exists,
  // we can render baseline vs would-be-enacted side-by-side.
  const variant = variants.find((v) => v.file_path === enc.file_path) ?? null;

  return (
    <div className="rulespec-panel rulespec-panel--encoded">
      <p className="rulespec-eyebrow">RuleSpec encoding</p>
      <h4 className="rulespec-title">
        <a href={enc.github_url} target="_blank" rel="noreferrer">
          {enc.file_path}
        </a>
      </h4>
      <dl className="rulespec-meta">
        <dt>Repo</dt><dd>{enc.repo}</dd>
        <dt>Kind</dt><dd>{enc.kind}</dd>
        <dt>Matches</dt><dd><code>{enc.citation}</code></dd>
      </dl>
      {variant ? (
        <RuleSpecVariantTabs variant={variant} />
      ) : (
        <p className="rulespec-hint">
          If this bill is enacted, Pipeline B will re-run the encoder
          against this file.
        </p>
      )}
    </div>
  );
}

function RuleSpecVariantTabs({ variant }: { variant: RuleVariant }) {
  const [tab, setTab] = useState<"current" | "enacted">("current");
  const hasPatched = !!variant.patched_yaml;
  return (
    <div className="rs-variant">
      <div className="rs-variant-tabs" role="tablist">
        <button
          role="tab" aria-selected={tab === "current"}
          className={`rs-variant-tab ${tab === "current" ? "on" : ""}`}
          onClick={() => setTab("current")}
        >
          Current
        </button>
        <button
          role="tab" aria-selected={tab === "enacted"}
          className={`rs-variant-tab ${tab === "enacted" ? "on" : ""}`}
          onClick={() => setTab("enacted")}
        >
          If enacted
          <span className={`rs-variant-tier rs-variant-tier--${variant.tier}`}>
            {variant.tier === "substitution" ? "auto" : variant.tier}
          </span>
        </button>
      </div>
      {tab === "current" ? (
        <pre className="rs-variant-yaml">{variant.baseline_yaml ?? "(baseline YAML not on disk)"}</pre>
      ) : hasPatched ? (
        <pre className="rs-variant-yaml">{variant.patched_yaml}</pre>
      ) : (
        <div className="rs-variant-todo">
          <p>{
            variant.tier === "structural"
              ? "Structural amendment — needs human or LLM-assisted re-encoding before a patched YAML can be produced."
              : variant.tier === "list"
              ? "Bill adds a list item — needs a human to author the new rule branch."
              : "No-op for this rule (no atom matched the bill's needle)."
          }</p>
          {variant.note && variant.tier !== "substitution" && (
            <p className="rs-variant-note">{variant.note.replace(/\s+/g, " ")}</p>
          )}
        </div>
      )}
    </div>
  );
}

function DiffView({ blocks }: { blocks: { kind: string; text: string }[] }) {
  return (
    <div className="diff-view">
      {blocks.map((b, i) => (
        <div key={i} className={`diff-block diff-block--${b.kind}`}>
          <span className="diff-gutter">
            {b.kind === "add" ? "+" : b.kind === "remove" ? "−" : " "}
          </span>
          <pre>{b.text || " "}</pre>
        </div>
      ))}
    </div>
  );
}
