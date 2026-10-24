import { useEffect, useRef, useState } from "react";
import { type Me, useAccount } from "../api/account";
import type { AuthMode } from "./AuthDialog";

interface Props {
  me: Me | undefined;
  onSignIn(mode: AuthMode): void;
  onSaved(): void;
}

export function AccountMenu({ me, onSignIn, onSaved }: Props) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState("");
  const { signOut, remove } = useAccount();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!me) return null;
  const user = me.user;
  if (!user) {
    return (
      <div className="account">
        <button onClick={() => onSignIn("signin")}>Sign in</button>
        {me.signups_open && (
          <button className="primary" onClick={() => onSignIn("signup")}>
            Create account
          </button>
        )}
      </div>
    );
  }

  const label = user.display_name || user.email;
  return (
    <div className="account picker" ref={box}>
      <button className="account-button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden>
          {label.slice(0, 1).toUpperCase()}
        </span>
        <span className="account-name">{label}</span>
      </button>
      {open && (
        <div className="popover account-popover" role="menu">
          <div className="small muted">Signed in as</div>
          <div className="account-email">{user.email}</div>
          <button
            className="ghost wide"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onSaved();
            }}
          >
            Saved searches
          </button>
          <button
            className="ghost wide"
            role="menuitem"
            disabled={signOut.isPending}
            onClick={() => signOut.mutate(undefined, { onSuccess: () => setOpen(false) })}
          >
            Sign out
          </button>
          {deleting ? (
            <form
              className="account-delete"
              onSubmit={(e) => {
                e.preventDefault();
                remove.mutate(password, { onSuccess: () => setOpen(false) });
              }}
            >
              <p className="small">
                This deletes your account with its watchlist, tasks, boards and saved searches. It can't be undone.
              </p>
              <input
                type="password"
                autoComplete="current-password"
                placeholder="Your password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {remove.error && <p className="error small">{remove.error.message}</p>}
              <div className="button-row">
                <button type="submit" className="danger" disabled={remove.isPending}>
                  Delete my account
                </button>
                <button type="button" className="ghost" onClick={() => setDeleting(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button className="link-button danger small" onClick={() => setDeleting(true)}>
              Delete account…
            </button>
          )}
        </div>
      )}
    </div>
  );
}
