import { clean } from "../lib/variant-text";

/** Side-by-side strike / insert block. Cleans whitespace + escape literals. */
export function BeforeAfter({
  kind, before, after,
}: { kind: string; before: string; after: string }) {
  const cleanedAfter = clean(after);
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
          <pre>{cleanedAfter || <em>(removed)</em>}</pre>
        </div>
      </div>
    </div>
  );
}
