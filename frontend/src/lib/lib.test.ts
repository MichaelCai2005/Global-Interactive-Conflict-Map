import { describe, expect, it } from "vitest";
import { axisTicks } from "../components/Timeline";
import { initialState, reducer, toSearch } from "../state/dashboard";
import {
  addDays,
  clampWindow,
  describeLength,
  fromDay,
  intervalFor,
  nextPeriod,
  previousWindow,
  shiftWindow,
  stepFor,
  toDay,
} from "./dates";
import { formatChange, percentChange } from "./format";
import { cellSizeForZoom, parseBbox, viewBbox } from "./geo";

describe("dates", () => {
  it("counts days from 1970 like the API does", () => {
    expect(toDay("1970-01-01")).toBe(0);
    expect(toDay("2022-02-20")).toBe(19043);
    expect(fromDay(19043)).toBe("2022-02-20");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
  });

  it("finds the start of the next bucket", () => {
    expect(nextPeriod("2022-01-31", "day")).toBe("2022-02-01");
    expect(nextPeriod("2022-02-28", "week")).toBe("2022-03-07");
    expect(nextPeriod("2022-12-01", "month")).toBe("2023-01-01");
  });

  it("picks coarser buckets for longer ranges", () => {
    expect(intervalFor("2022-01-01", "2022-06-30")).toBe("day");
    expect(intervalFor("2021-01-01", "2022-12-31")).toBe("week");
    expect(intervalFor("1989-01-01", "2025-12-31")).toBe("month");
  });

  it("moves a window without leaving the domain or changing its length", () => {
    const domain = { start: "2022-01-01", end: "2022-12-31" };
    const window = { start: "2022-12-01", end: "2022-12-14" };
    expect(shiftWindow(window, 7, domain)).toEqual({ start: "2022-12-08", end: "2022-12-21" });
    expect(shiftWindow(window, 30, domain)).toEqual({ start: "2022-12-18", end: "2022-12-31" });
    expect(shiftWindow(window, -1000, domain)).toEqual({ start: "2022-01-01", end: "2022-01-14" });
  });

  it("steps playback by about a quarter of the window", () => {
    expect(stepFor({ start: "2022-01-01", end: "2022-01-03" })).toBe(1);
    expect(stepFor({ start: "2022-01-01", end: "2022-01-14" })).toBe(4);
    expect(stepFor({ start: "2022-01-01", end: "2022-01-30" })).toBe(7);
    expect(stepFor({ start: "2022-01-01", end: "2022-12-31" })).toBe(30);
  });

  it("compares with the window just before, of the same length", () => {
    expect(previousWindow({ start: "2022-03-01", end: "2022-03-31" })).toEqual({
      start: "2022-01-29",
      end: "2022-02-28",
    });
  });

  it("clamps windows into the domain", () => {
    const domain = { start: "2020-01-01", end: "2020-12-31" };
    expect(clampWindow({ start: "2019-06-01", end: "2020-02-01" }, domain)).toEqual({
      start: "2020-01-01",
      end: "2020-02-01",
    });
    // A window entirely outside falls back to the whole domain.
    expect(clampWindow({ start: "2021-01-01", end: "2021-02-01" }, domain)).toEqual(domain);
  });

  it("describes window lengths in words", () => {
    expect(describeLength(7)).toBe("week");
    expect(describeLength(30)).toBe("month");
    expect(describeLength(365)).toBe("year");
    expect(describeLength(14)).toBe("2 weeks");
    expect(describeLength(10)).toBe("10 days");
  });
});

describe("timeline axis", () => {
  it("labels years for long ranges and months for shorter ones", () => {
    const years = axisTicks({ start: "1989-01-01", end: "2025-12-31" }, 700);
    expect(years.length).toBeLessThanOrEqual(10);
    expect(years.every((t) => /^\d{4}$/.test(t.label))).toBe(true);

    const months = axisTicks({ start: "2022-01-01", end: "2022-12-31" }, 1000);
    expect(months.map((t) => t.label).slice(0, 3)).toEqual(["2022", "Feb", "Mar"]);
  });
});

describe("geo", () => {
  it("chooses grid cells of roughly constant on-screen size", () => {
    expect(cellSizeForZoom(1)).toBe(8);
    expect(cellSizeForZoom(3)).toBe(2);
    expect(cellSizeForZoom(6)).toBe(0.25);
  });

  it("returns no bbox for world views or views across the antimeridian", () => {
    expect(viewBbox(-200, -80, 200, 80)).toBeNull();
    expect(viewBbox(170, -10, 190, 10)).toBeNull();
    expect(viewBbox(30.04, 44.96, 40.01, 52.5)).toEqual([30, 44.9, 40.1, 52.5]);
  });

  it("parses only valid bbox strings", () => {
    expect(parseBbox("36,47,40,50")).toEqual([36, 47, 40, 50]);
    expect(parseBbox("40,47,36,50")).toBeNull();
    expect(parseBbox("1,2,3")).toBeNull();
    expect(parseBbox(null)).toBeNull();
  });
});

describe("format", () => {
  it("reports change, or 'new' when there was nothing before", () => {
    expect(formatChange(percentChange(150, 100))).toBe("+50%");
    expect(formatChange(percentChange(50, 100))).toBe("-50%");
    expect(formatChange(percentChange(5, 0))).toBe("new");
    expect(formatChange(percentChange(0, 0))).toBe("no change");
    expect(formatChange(percentChange(1000, 10))).toBe("100×");
  });
});

describe("dashboard state", () => {
  it("round-trips through the URL", () => {
    let state = initialState("");
    state = reducer(state, { type: "filters", filters: { sources: ["ucdp"], country: "Ukraine", violence: "violent" } });
    state = reducer(state, { type: "window", window: { start: "2022-02-01", end: "2022-02-28" } });
    state = reducer(state, { type: "select", eventId: 42 });
    state = reducer(state, { type: "panel", panel: "tasks" });
    const restored = initialState(`?${toSearch(state)}`);
    expect(restored.filters).toEqual(state.filters);
    expect(restored.window).toEqual(state.window);
    expect(restored.selectedEventId).toBe(42);
    expect(restored.panel).toBe("tasks");
    expect(restored.camera.zoom).toBeCloseTo(state.camera.zoom, 2);
  });

  it("ignores malformed URL values", () => {
    const state = initialState("?from=yesterday&to=2022-01-01&class=maybe&event=-3&at=a,b,c");
    expect(state.window).toBeNull();
    expect(state.filters.violence).toBe("all");
    expect(state.selectedEventId).toBeNull();
    expect(state.camera.zoom).toBeGreaterThan(0);
  });

  it("starts a story with a cleared filter set and playback on", () => {
    let state = initialState("?country=Syria");
    state = reducer(state, { type: "story", range: { start: "2022-01-01", end: "2022-12-31" }, windowDays: 14 });
    expect(state.filters.country).toBeNull();
    expect(state.window).toEqual({ start: "2022-01-01", end: "2022-01-14" });
    expect(state.playing).toBe(true);
  });
});
