import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facets } from "../api/types";
import { DISCOVERIES, useDiscoveries } from "../lib/discover";
import { EMPTY_FILTERS } from "../state/dashboard";
import { FilterBar } from "./FilterBar";
import { ThingsToTry } from "./ThingsToTry";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("useDiscoveries", () => {
  it("ticks things off once and remembers them in this browser", () => {
    const { result } = renderHook(() => useDiscoveries());
    expect(result.current.done.size).toBe(0);
    act(() => result.current.mark("risk"));
    const after = result.current.done;
    act(() => result.current.mark("risk"));
    // Marking again changes nothing, so effects that mark on every render don't loop.
    expect(result.current.done).toBe(after);
    expect(renderHook(() => useDiscoveries()).result.current.done.has("risk")).toBe(true);
  });

  it("ignores what it doesn't recognise in storage", () => {
    localStorage.setItem("conflict-map:discovered", '["event","gone"]');
    expect([...renderHook(() => useDiscoveries()).result.current.done]).toEqual(["event"]);
    localStorage.setItem("conflict-map:discovered", "not json");
    expect(renderHook(() => useDiscoveries()).result.current.done.size).toBe(0);
  });
});

describe("ThingsToTry", () => {
  it("suggests the next thing, and lists them all on request", async () => {
    const onShow = vi.fn();
    render(<ThingsToTry items={DISCOVERIES} done={new Set(["event"])} onShow={onShow} onHide={() => {}} />);
    expect(screen.getByText(`1 of ${DISCOVERIES.length}`)).toBeTruthy();
    expect(screen.getByText("Move through time")).toBeTruthy();
    expect(screen.queryByText("See where risk is rising")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Show me" }));
    expect(onShow).toHaveBeenCalledWith(DISCOVERIES[1]);

    await userEvent.click(screen.getByRole("button", { name: "Show them all" }));
    expect(screen.getByText("See where risk is rising")).toBeTruthy();
    // Done things have nothing left to show.
    expect(screen.getAllByRole("button", { name: "Show me" })).toHaveLength(DISCOVERIES.length - 1);
  });

  it("says when everything has been tried", () => {
    render(
      <ThingsToTry items={DISCOVERIES} done={new Set(DISCOVERIES.map((d) => d.key))} onShow={() => {}} onHide={() => {}} />,
    );
    expect(screen.getByText(/You've tried everything/)).toBeTruthy();
  });
});

describe("FilterBar", () => {
  const facets: Facets = {
    sources: [{ value: "ucdp", count: 10, first_date: "1989-01-01", last_date: "2026-09-30" }],
    event_types: [],
    countries: [],
    first_date: "1989-01-01",
    last_date: "2026-10-25",
  };

  it("keeps sources behind More filters until wanted", async () => {
    render(<FilterBar facets={facets} filters={EMPTY_FILTERS} onChange={() => {}} onClear={() => {}} />);
    expect(screen.queryByRole("button", { name: "UCDP" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    expect(screen.getByRole("button", { name: "UCDP" })).toBeTruthy();
  });

  it("never hides a source filter in force", () => {
    render(
      <FilterBar facets={facets} filters={{ ...EMPTY_FILTERS, sources: ["ucdp"] }} onChange={() => {}} onClear={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "UCDP" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: "More filters" })).toBeNull();
  });
});
