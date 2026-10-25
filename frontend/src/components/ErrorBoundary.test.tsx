import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Broken(): never {
  throw new Error("Invalid 1 panel layout: 100%, 0%");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("ErrorBoundary", () => {
  it("shows its children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>The map</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("The map")).toBeTruthy();
  });

  it("replaces a crash with a message, the error and a way back, and drops the loading screen", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const splash = document.createElement("div");
    splash.id = "splash";
    document.body.append(splash);

    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert").textContent).toContain("Something went wrong");
    expect(screen.getByText(/Invalid 1 panel layout/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start over" })).toBeTruthy();
    expect(splash.classList.contains("is-done")).toBe(true);
  });
});
