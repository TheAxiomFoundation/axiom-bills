// Readable rendering of the RuleSpec rules a bill section touches:
// one card per rule with its grounding quotes and formatted formula,
// instead of raw YAML in a <pre>. Loaded via React.lazy from BillDiffs
// so the yaml parser stays out of the main bundle.
//
// All parsing/derivation lives in ../lib/rulespec-view (pure, tested);
// this file only renders.

import type { AmendmentOp } from "../lib/api";
import { buildRuleCards, type RuleAtom } from "../lib/rulespec-view";

const ATOM_KIND_LABEL: Record<string, string> = {
  formula: "encodes",
  condition: "condition",
  exception: "exception",
  amount: "amount",
  import: "imports",
};

function AtomRow({ atom }: { atom: RuleAtom }) {
  if (atom.importTarget) {
    const [, fragment] = atom.importTarget.split("#");
    return (
      <li className="rs-atom rs-atom--import">
        <em className="rs-atom-kind">{ATOM_KIND_LABEL.import}</em>
        <code>{fragment ?? atom.importTarget}</code>
      </li>
    );
  }
  if (!atom.excerpt) return null;
  return (
    <li className={`rs-atom ${atom.struck ? "rs-atom--struck" : ""}`}>
      <em className="rs-atom-kind">
        {ATOM_KIND_LABEL[atom.kind] ?? atom.kind}
      </em>
      <blockquote>“{atom.excerpt}”</blockquote>
      {atom.struck ? (
        <span className="rs-atom-struck-note">
          this bill amends the quoted text
        </span>
      ) : null}
    </li>
  );
}

export default function RuleSpecRules({
  yamlText,
  sectionCitation,
  ops,
}: {
  yamlText: string;
  sectionCitation: string;
  ops: AmendmentOp[];
}) {
  const parsed = buildRuleCards(yamlText, sectionCitation, ops);

  // Parser couldn't make sense of the file — fall back to the raw text
  // rather than showing nothing.
  if (parsed.error) {
    return <pre className="rs-variant-yaml">{yamlText}</pre>;
  }

  // YAML parsed but no rule grounds in this citation. The gate upstream
  // (BillDiffs' line-based baseline slicer) and the YAML matcher here
  // can disagree — different parser, and this may be the PATCHED file —
  // so never render an empty card list: explain, then show the file.
  if (parsed.cards.length === 0) {
    return (
      <div className="rs-rule-cards rs-rule-cards--fallback">
        <p className="hint">
          No rule in this file grounds in <code>{sectionCitation}</code> —
          showing the whole file instead.
        </p>
        <pre className="rs-variant-yaml">{yamlText}</pre>
      </div>
    );
  }

  return (
    <div className="rs-rule-cards">
      {parsed.cards.map((card) => (
        <article className="rs-rule-card" key={card.name}>
          <header className="rs-rule-card-head">
            <code className="rs-rule-card-name">{card.name}</code>
            <span className="rs-rule-card-chips">
              <em className={`impact-rule-kind impact-rule-kind--${card.kind}`}>
                {card.kind}
              </em>
              {[card.dtype, card.entity, card.period]
                .filter(Boolean)
                .map((chip) => (
                  <em className="rs-rule-card-chip" key={chip}>
                    {chip}
                  </em>
                ))}
            </span>
          </header>
          <p className="rs-rule-card-source">
            grounds in <code>{card.source}</code>
          </p>

          {card.atoms.length > 0 ? (
            <ul className="rs-atom-list">
              {card.atoms.map((atom, i) => (
                <AtomRow atom={atom} key={i} />
              ))}
            </ul>
          ) : null}

          {card.versions.map((v, i) => (
            <div className="rs-rule-formula" key={i}>
              <p className="rs-rule-formula-label">
                formula{v.effectiveFrom ? ` · from ${v.effectiveFrom}` : ""}
              </p>
              <pre>{v.formula}</pre>
            </div>
          ))}
        </article>
      ))}
    </div>
  );
}
