import { ALL_KINDS, type BillKind, type KindCounts } from "../lib/api";
import { KIND_LABEL } from "../lib/format";
import { Dropdown } from "./Dropdown";

type Props = {
  selected: BillKind[];
  onChange: (next: BillKind[]) => void;
  counts?: KindCounts;
};

// Multi-select kinds dropdown. Empty selection isn't a valid state — we
// fall back to substantive automatically. That avoids the "I unselected
// everything and saw nothing" pit of failure.
export function KindFilter({ selected, onChange, counts }: Props) {
  const toggle = (k: BillKind) => {
    if (selected.includes(k)) {
      const next = selected.filter((x) => x !== k);
      onChange(next.length ? next : ["substantive"]);
    } else {
      onChange([...selected, k]);
    }
  };

  const summary = selected.length === 1
    ? KIND_LABEL[selected[0]]
    : `${selected.length} selected`;

  return (
    <Dropdown label="Kinds" summary={summary}>
      <ul className="dropdown-list">
        {ALL_KINDS.map((k) => {
          const on = selected.includes(k);
          const n = counts?.[k] ?? 0;
          return (
            <li key={k}>
              <label className={`dropdown-option ${n === 0 ? "empty" : ""}`}>
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(k)}
                />
                <span className="dropdown-option-label">{KIND_LABEL[k]}</span>
                <span className="dropdown-option-count">{n}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </Dropdown>
  );
}
