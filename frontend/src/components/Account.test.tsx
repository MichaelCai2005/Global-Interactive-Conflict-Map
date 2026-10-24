import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../api/account";
import { AccountMenu } from "./AccountMenu";
import { AuthDialog } from "./AuthDialog";
import { describeQuery } from "./SavedPanel";

const SIGNED_IN: Me = {
  user: { id: 1, email: "ana@example.org", display_name: "Ana", created_at: "2026-10-21T00:00:00Z" },
  workspace: "personal",
  signups_open: true,
};

function mockApi(respond: (url: string, init: RequestInit) => Response) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => respond(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderWithQueries(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AuthDialog", () => {
  it("creates an account and closes", async () => {
    const fetchMock = mockApi(() => json(SIGNED_IN, 201));
    const onClose = vi.fn();
    renderWithQueries(<AuthDialog mode="signup" signupsOpen onClose={onClose} />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.org");
    await userEvent.type(screen.getByLabelText(/^Password/), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/auth/signup");
    expect(JSON.parse(String(init?.body))).toMatchObject({ email: "ana@example.org", password: "correct horse" });
  });

  it("shows why signing in failed", async () => {
    mockApi(() => json({ detail: "Wrong email or password" }, 401));
    const onClose = vi.fn();
    renderWithQueries(<AuthDialog mode="signin" signupsOpen onClose={onClose} />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.org");
    await userEvent.type(screen.getByLabelText(/^Password/), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Wrong email or password");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("only offers signing in when the site takes no new accounts", () => {
    renderWithQueries(<AuthDialog mode="signup" signupsOpen={false} onClose={() => {}} />);
    expect(screen.getByRole("heading").textContent).toBe("Sign in");
    expect(screen.queryByText("Create an account")).toBeNull();
  });
});

describe("AccountMenu", () => {
  it("offers to sign in to a visitor", async () => {
    const onSignIn = vi.fn();
    renderWithQueries(
      <AccountMenu me={{ ...SIGNED_IN, user: null, workspace: null }} onSignIn={onSignIn} onSaved={() => {}} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(onSignIn).toHaveBeenCalledWith("signup");
  });

  it("signs out", async () => {
    const fetchMock = mockApi(() => new Response(null, { status: 204 }));
    renderWithQueries(<AccountMenu me={SIGNED_IN} onSignIn={() => {}} onSaved={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Ana/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/auth/logout");
  });
});

describe("describeQuery", () => {
  it("reads a saved view's window and filters", () => {
    expect(describeQuery("from=2024-01-01&to=2024-03-31&country=Sudan&class=violent")).toMatch(
      /2024.*Sudan · violence only$/,
    );
    expect(describeQuery("at=1,2,3")).toBe("Whole map");
  });
});
