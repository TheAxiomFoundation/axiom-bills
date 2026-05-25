import { Link, Outlet } from "react-router-dom";

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span>Axiom</span>
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
