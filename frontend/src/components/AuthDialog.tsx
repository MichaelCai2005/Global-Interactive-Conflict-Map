import { useState } from "react";
import { useAccount } from "../api/account";

export type AuthMode = "signin" | "signup";

interface Props {
  mode: AuthMode;
  signupsOpen: boolean;
  onClose(): void;
}

export function AuthDialog({ mode: initial, signupsOpen, onClose }: Props) {
  const [mode, setMode] = useState<AuthMode>(signupsOpen ? initial : "signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const { signIn, signUp } = useAccount();
  const action = mode === "signin" ? signIn : signUp;
  const signingUp = mode === "signup";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const body = signingUp ? { email, password, display_name: name } : { email, password };
    action.mutate(body, { onSuccess: onClose });
  };

  const switchTo = (next: AuthMode) => {
    setMode(next);
    signIn.reset();
    signUp.reset();
  };

  return (
    <div className="welcome-backdrop" onClick={onClose}>
      <div
        className="welcome auth-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <button className="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <h2 id="auth-title">{signingUp ? "Create an account" : "Sign in"}</h2>
        <p className="small">
          Your watchlist, tasks, boards and saved searches are kept with your account, so they're there on any
          computer you sign in from.
        </p>
        <form className="auth-form" onSubmit={submit}>
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          {signingUp && (
            <label>
              <span>
                Name <span className="muted">(optional)</span>
              </span>
              <input autoComplete="name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          )}
          <label>
            <span>
              Password {signingUp && <span className="muted">(at least 8 characters)</span>}
            </span>
            <input
              type="password"
              autoComplete={signingUp ? "new-password" : "current-password"}
              required
              minLength={signingUp ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {action.error && (
            <p className="error small" role="alert">
              {action.error.message}
            </p>
          )}
          <button type="submit" className="primary" disabled={action.isPending}>
            {action.isPending ? "One moment…" : signingUp ? "Create account" : "Sign in"}
          </button>
        </form>
        {signupsOpen && (
          <p className="small muted auth-switch">
            {signingUp ? "Already have an account? " : "New here? "}
            <button className="link-button" onClick={() => switchTo(signingUp ? "signin" : "signup")}>
              {signingUp ? "Sign in" : "Create an account"}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

/** Shown in place of a personal panel to a visitor who isn't signed in. */
export function SignInPrompt({ what, onSignIn }: { what: string; onSignIn(mode: AuthMode): void }) {
  return (
    <div className="panel-body">
      <div className="empty sign-in-prompt">
        <p>Sign in to keep {what}. It's saved to your account, so it's there whenever you come back.</p>
        <div className="button-row">
          <button className="primary" onClick={() => onSignIn("signin")}>
            Sign in
          </button>
          <button onClick={() => onSignIn("signup")}>Create an account</button>
        </div>
      </div>
    </div>
  );
}
