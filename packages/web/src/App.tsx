import { Link, Outlet } from "react-router-dom";

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          {/* Settled brand lockup (w350, outlined paths) — never a live-font wordmark. */}
          <img
            src={`${import.meta.env.BASE_URL}axiom-foundation.svg`}
            alt="Axiom Foundation"
          />
        </Link>
        <nav>
          <Link to="/">Jurisdictions</Link>
          <Link to="/coverage">Coverage</Link>
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
