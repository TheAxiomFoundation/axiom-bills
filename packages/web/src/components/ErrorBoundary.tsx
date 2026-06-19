import { Component, type ErrorInfo, type ReactNode } from "react";
import { errorMessage } from "../lib/errors";

type Props = { children: ReactNode };
type State = { error: Error | null };

// Stops a render-time crash in any one page from blanking the whole app.
// Without this, an unexpected exception (or a thrown module-init error like
// missing Supabase env vars) leaves users staring at a white screen.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep a console breadcrumb for debugging in production.
    console.error("Render error caught by ErrorBoundary:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="app">
          <main>
            <p className="page-eyebrow">§ error</p>
            <h1>Something went wrong.</h1>
            <p className="error">{errorMessage(this.state.error)}</p>
            <p className="hint">
              <button type="button" onClick={() => window.location.reload()}>
                Reload the page
              </button>
            </p>
          </main>
        </div>
      );
    }
    return this.props.children;
  }
}
