import type { NormalizedStatus } from "../lib/api";
import { STATUS_COLOR, STATUS_LABEL } from "../lib/format";

// Editorial badge: outlined pill, color = ink hue for the status. The badge
// component intentionally uses currentColor for border + text so the same
// CSS rule drives both — keeps the look consistent on the paper surface.
export function StatusBadge({ status }: { status: NormalizedStatus }) {
  return (
    <span className="badge" style={{ color: STATUS_COLOR[status] }}>
      {STATUS_LABEL[status]}
    </span>
  );
}
