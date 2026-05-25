import type { NormalizedStatus } from "../lib/api";
import { STATUS_LABEL } from "../lib/format";

const OPTIONS: { value: NormalizedStatus | ""; label: string }[] = [
  { value: "",                label: "All statuses" },
  { value: "introduced",      label: STATUS_LABEL.introduced },
  { value: "in_committee",    label: STATUS_LABEL.in_committee },
  { value: "passed_chamber",  label: STATUS_LABEL.passed_chamber },
  { value: "passed_both",     label: STATUS_LABEL.passed_both },
  { value: "enrolled",        label: STATUS_LABEL.enrolled },
  { value: "signed",          label: STATUS_LABEL.signed },
  { value: "enacted",         label: STATUS_LABEL.enacted },
  { value: "vetoed",          label: STATUS_LABEL.vetoed },
];

type Props = {
  value: NormalizedStatus | "";
  onChange: (next: NormalizedStatus | "") => void;
};

// Status is single-select, so native <select> is the right primitive.
// Styled as a pill to match the kind dropdown trigger.
export function StatusFilter({ value, onChange }: Props) {
  return (
    <label className="status-select">
      <span className="dropdown-label">Status</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as NormalizedStatus | "")}
      >
        {OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
