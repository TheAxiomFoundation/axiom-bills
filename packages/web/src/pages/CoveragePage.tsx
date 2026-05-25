import { Link } from "react-router-dom";
import { CoverageSection } from "../components/CoverageSection";

export function CoveragePage() {
  return (
    <div>
      <p className="crumb"><Link to="/">← Jurisdictions</Link></p>
      <CoverageSection />
    </div>
  );
}
