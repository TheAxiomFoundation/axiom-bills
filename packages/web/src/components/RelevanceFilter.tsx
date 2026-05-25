import type { Relevance } from "../lib/api";

const OPTIONS: { value: Relevance; label: string }[] = [
  { value: "any",              label: "All bills" },
  { value: "touches_corpus",   label: "Touches Axiom corpus" },
  { value: "touches_rulespec", label: "Touches a RuleSpec" },
];

type Props = {
  value: Relevance;
  onChange: (next: Relevance) => void;
};

// Single-select dropdown — mirrors the StatusFilter shape so the three
// jurisdiction-page filters (kinds, status, relevance) read as one row.
export function RelevanceFilter({ value, onChange }: Props) {
  return (
    <label className="status-select">
      <span className="dropdown-label">Relevance</span>
      <select value={value} onChange={(e) => onChange(e.target.value as Relevance)}>
        {OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
