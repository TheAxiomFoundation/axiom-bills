import { Link, Outlet } from "react-router-dom";

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">axiom-bills</Link>
        <nav>
          <Link to="/">Jurisdictions</Link>
          <Link to="/recent">Recently enacted</Link>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
      <footer>
        Prototype · feeds Pipeline B of the Axiom auto-update layer.
      </footer>
    </div>
  );
}
