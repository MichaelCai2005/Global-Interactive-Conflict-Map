import { Component, type ErrorInfo, type ReactNode } from "react";
import { hideSplash } from "../lib/splash";
import { BrandMark } from "./BrandMark";

interface State {
  error: Error | null;
}

// Without this, an error thrown while rendering unmounts the whole app and leaves a blank
// page. It shows what went wrong and a way back instead.
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("The app crashed:", error, info.componentStack);
    // The loading screen sits above everything, so it would hide this message.
    hideSplash();
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash" role="alert">
        <BrandMark size={40} />
        <h1>Something went wrong</h1>
        <p>
          The page hit an error it couldn't recover from. Reloading usually fixes it. If it keeps happening, start
          over: that drops the view saved in the address bar, such as an open board.
        </p>
        <div className="button-row">
          <button className="primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <button onClick={() => window.location.assign(window.location.pathname)}>Start over</button>
        </div>
        <details>
          <summary>Error details</summary>
          <pre>{error.stack ?? error.message}</pre>
        </details>
      </div>
    );
  }
}
