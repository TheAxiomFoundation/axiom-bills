import type { NormalizedStatus } from "../lib/api";
import { STATUS_COLOR, STATUS_LABEL } from "../lib/format";

export function StatusBadge({ status }: { status: NormalizedStatus }) {
  return (
    <span className="badge" style={{ background: STATUS_COLOR[status] }}>
      {STATUS_LABEL[status]}
    </span>
  );
}
