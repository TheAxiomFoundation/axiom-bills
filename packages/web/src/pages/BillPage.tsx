import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type BillDetail } from "../lib/api";
import { BillDiffs } from "../components/BillDiffs";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate, KIND_LABEL } from "../lib/format";
import { errorMessage } from "../lib/errors";
import { retry } from "../lib/retry";

// Turn GPO plain-text into proper paragraphs.
//
// GPO format:
//   - Header chrome at top: "[Congressional Bills ...]", "<DOC>", etc.
//   - Resolutions/findings: each "Whereas X;" is logically a paragraph,
//     but GPO writes them as `Whereas X\n        continuation Y;\n` —
//     a leading line at col 0 plus continuation lines indented ~8 spaces.
//     No blank line between paragraphs.
//   - Resolved clauses: `Resolved, That...` plus numbered items `(1)`,
//     `(2)`, indented at col 12.
//   - Section headers (RESOLUTION, IN THE HOUSE OF REPRESENTATIVES,
//     SECTION 1., etc.) surrounded by horizontal rules of underscores.
//
// We strip the header chrome, then insert paragraph breaks before known
// starters so that join-on-paragraph and collapse-within-paragraph
// produces readable prose.
type BillTextRow = BillDetail["texts"][number];

function BillTextSection({
  texts,
  open,
  onToggle,
  activeIdx,
  onActiveChange,
}: {
  texts: BillTextRow[];
  open: boolean;
  onToggle: () => void;
  activeIdx: number;
  onActiveChange: (idx: number) => void;
}) {
  const active = texts[activeIdx];
  const paragraphs = useMemo(() => {
    if (!active) return [];
    return cleanBillText(active.text).split("\n\n");
  }, [active]);

  return (
    <section>
      <div className="bill-text-header">
        <h3>Bill text</h3>
        <button
          className="bill-text-toggle"
          onClick={onToggle}
          aria-expanded={open}
        >
          {open ? "Hide" : "Show"} ({texts.length} version{texts.length === 1 ? "" : "s"})
        </button>
      </div>

      {open && (
        <>
          {texts.length > 1 && (
            <label className="bill-text-select">
              <span className="dropdown-label">Version</span>
              <select
                value={activeIdx}
                onChange={(e) => onActiveChange(Number(e.target.value))}
              >
                {texts.map((t, i) => (
                  <option key={i} value={i}>
                    {t.version_label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="bill-text-box">
            <div className="bill-text">
              {paragraphs.map((p, i) => {
                const isHeading = /^[A-Z][A-Z ,.'-]{2,}[A-Z.]$/.test(p.trim());
                return isHeading ? (
                  <p key={i} className="bill-text-heading">{p}</p>
                ) : (
                  <p key={i}>{p}</p>
                );
              })}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function cleanBillText(raw: string): string {
  let text = raw
    .replace(/\[Congressional Bills[^\]]+\]/i, "")
    .replace(/\[From the U\.S\. Government Publishing Office\]/i, "")
    .replace(/\[[A-Z][^\]]+\]/, "")
    .replace(/<DOC>/g, "")
    // Horizontal rules → paragraph break.
    .replace(/^_+$/gm, "\n")
    // Centered all-caps headings (RESOLUTION, IN THE HOUSE OF...) →
    // their own paragraph by injecting blank lines around them.
    .replace(/\n(\s*[A-Z][A-Z ,.'-]{2,}[A-Z.])\n/g, "\n\n$1\n\n");

  // Inject blank lines before paragraph starters that GPO writes
  // back-to-back without them.
  text = text
    .replace(/\n(?=Whereas\b)/g, "\n\n")
    .replace(/\n(?=Resolved,)/g, "\n\n")
    .replace(/\n(?=Be it (enacted|resolved))/g, "\n\n")
    .replace(/\n(?=Sec(tion)?\.?\s+\d)/gi, "\n\n")
    .replace(/\n(\s*\(\d+\))/g, "\n\n$1");

  return text
    .split(/\n\s*\n+/)
    .map((p) => p.replace(/\s*\n\s*/g, " ").replace(/\s{2,}/g, " ").trim())
    .filter(Boolean)
    .join("\n\n");
}

export function BillPage() {
  const { billId = "" } = useParams();
  const [bill, setBill] = useState<BillDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [textOpen, setTextOpen] = useState(false);
  const [activeTextIdx, setActiveTextIdx] = useState(0);

  useEffect(() => {
    retry(() => api.bill(billId)).then(setBill).catch((e) => setErr(errorMessage(e)));
  }, [billId]);

  // Whenever we navigate to a different bill, collapse the text panel
  // and reset to the newest version.
  useEffect(() => {
    setTextOpen(false);
    setActiveTextIdx(0);
  }, [billId]);

  if (err) return <p className="error">{err}</p>;
  if (!bill) return <p>Loading…</p>;

  return (
    <div>
      <p className="crumb">
        <Link to="/">Jurisdictions</Link>
        {"  ·  "}
        <Link to={`/j/${bill.jurisdiction}`}>{bill.jurisdiction_name}</Link>
      </p>

      <header className="bill-header">
        <h1>{bill.number}</h1>
        <a href={bill.source_url} target="_blank" rel="noreferrer">source ↗</a>
      </header>

      <p className="bill-title">{bill.title || <em>untitled</em>}</p>
      <div className="session">
        <span className="session-meta">
          {bill.session_name} · chamber: {bill.chamber}
        </span>
        <StatusBadge status={bill.current_status} />
        <span className={`kind-chip kind-chip--${bill.kind}`}>
          {KIND_LABEL[bill.kind]}
        </span>
      </div>

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

      <BillDiffs billId={bill.id} />

      {bill.texts.length > 0 && (
        <BillTextSection
          texts={bill.texts}
          open={textOpen}
          onToggle={() => setTextOpen((x) => !x)}
          activeIdx={Math.min(activeTextIdx, bill.texts.length - 1)}
          onActiveChange={setActiveTextIdx}
        />
      )}

      <section>
        <h3>Actions</h3>
        <ol className="timeline">
          {bill.actions.map((a, i) => (
            <li key={i}>
              <time>{fmtDate(a.occurred_at)}</time>
              <div>
                <p>{a.action_text}</p>
                <div className="action-meta">
                  {a.normalized_status && a.normalized_status !== "unknown" && (
                    <StatusBadge status={a.normalized_status} />
                  )}
                  {a.versions.length > 0 && (
                    <span className="action-versions">
                      <span className="action-versions-label">Text:</span>
                      {a.versions.map((v) => (
                        <a
                          key={v.format}
                          href={v.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="action-version-link"
                        >
                          {v.format}
                        </a>
                      ))}
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {bill.unclaimed_versions.length > 0 && (
        <section>
          <h3>Other versions</h3>
          <p className="hint">
            Printings we couldn’t pin to a specific action above.
          </p>
          <ul className="unclaimed-versions">
            {bill.unclaimed_versions.map((u) => (
              <li key={u.stage}>
                <span className="unclaimed-stage">{u.stage_label}</span>
                <span className="action-versions">
                  {u.formats.map((f) => (
                    <a
                      key={f.format}
                      href={f.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="action-version-link"
                    >
                      {f.format}
                    </a>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
