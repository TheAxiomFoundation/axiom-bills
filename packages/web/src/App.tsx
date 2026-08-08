import { Link, Outlet } from "react-router-dom";

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-group">
          <a
            href="https://axiom-foundation.org"
            className="brand"
            aria-label="Axiom Foundation"
          >
            {/* Settled brand lockup (w350, outlined paths) — never a live-font wordmark.
                BASE_URL-relative: the app deploys under axiom.org/bills. */}
            <img
              src={`${import.meta.env.BASE_URL}axiom-foundation.svg`}
              alt="Axiom Foundation"
            />
          </a>
          <Link to="/" className="brand-title">
            <span className="brand-name">Bills</span>
          </Link>
        </div>
        <nav>
          <Link to="/">Jurisdictions</Link>
          <Link to="/coverage">Coverage</Link>
          <a href="https://axiom.org/demos" className="all-demos">
            All demos
          </a>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
      <footer>
        Prototype · feeds Pipeline B of the Axiom auto-update layer
      </footer>
    </div>
  );
}
