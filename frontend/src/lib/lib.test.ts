import { describe, expect, it } from "vitest";
import { axisTicks } from "../components/Timeline";
import { initialState, reducer, toSearch } from "../state/dashboard";
import { cellCategory, eventCategory, kindCategory, kindLabel } from "./categories";
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
import { formatChange, percentChange, placeLabel } from "./format";
import { cellSizeForZoom, parseBbox, viewBbox } from "./geo";
import {
  deathsThrough,
  describeAge,
  describeTimeAgo,
  headlineFromUrl,
  latestWindow,
  oneEachStory,
  reportedSince,
} from "./now";

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

  it("opens a plain visit on the Now tab, and a link without a panel on the overview", () => {
    expect(initialState("").panel).toBe("now");
    expect(initialState("?country=Syria").panel).toBe("overview");
    expect(initialState("?panel=now&country=Syria").panel).toBe("now");
  });

  it("starts a story with a cleared filter set and playback on", () => {
    let state = initialState("?country=Syria");
    state = reducer(state, { type: "story", range: { start: "2022-01-01", end: "2022-12-31" }, windowDays: 14 });
    expect(state.filters.country).toBeNull();
    expect(state.window).toEqual({ start: "2022-01-01", end: "2022-01-14" });
    expect(state.playing).toBe(true);
  });
});

describe("now", () => {
  const sources = [
    { value: "gdelt", count: 9, first_date: "2012-02-27", last_date: "2026-10-23" },
    { value: "ucdp", count: 5, first_date: "1989-01-01", last_date: "2026-09-30" },
    { value: "acled", count: 3, first_date: "2018-01-01", last_date: "2022-12-31" },
  ];

  it("takes the newest days of data, not the days up to today", () => {
    expect(latestWindow("2026-10-23", 7)).toEqual({ start: "2026-10-17", end: "2026-10-23" });
    expect(latestWindow("2026-10-23", 1)).toEqual({ start: "2026-10-23", end: "2026-10-23" });
  });

  it("finds the newest death counts among the sources the filters allow", () => {
    expect(deathsThrough(sources, [])).toBe("2026-09-30");
    expect(deathsThrough(sources, ["acled", "gdelt"])).toBe("2022-12-31");
    expect(deathsThrough(sources, ["gdelt"])).toBeNull();
  });

  it("says how long ago a date was", () => {
    expect(describeAge("2026-10-24", "2026-10-24")).toBe("today");
    expect(describeAge("2026-10-23", "2026-10-24")).toBe("yesterday");
    expect(describeAge("2026-10-19", "2026-10-24")).toBe("5 days ago");
    expect(describeAge("2026-09-30", "2026-10-24")).toBe("3 weeks ago");
    expect(describeAge("2022-12-31", "2026-10-24")).toBe("4 years ago");
  });

  it("reads a headline out of a news link", () => {
    expect(
      headlineFromUrl("https://www.cp24.com/news/canada/2026/10/18/fatalities-and-injuries-reported-after-incident/"),
    ).toBe("Fatalities and injuries reported after incident");
    expect(headlineFromUrl("https://www.mirror.co.uk/news/world-news/paris-shooting-trappes-police-dead-37803230")).toBe(
      "Paris shooting trappes police dead",
    );
    expect(headlineFromUrl("https://www.heraldseries.co.uk/news/26667668.musk-speaks-starlink-service-ukraine/")).toBe(
      "Musk speaks starlink service ukraine",
    );
    expect(headlineFromUrl("https://www.kyivpost.com/post/87476")).toBeNull();
    expect(headlineFromUrl("not a link")).toBeNull();
  });

  it("names a place without repeating its country", () => {
    expect(placeLabel("Kyiv, Kyyiv, Misto, Ukraine", "Ukraine")).toBe("Kyiv, Kyyiv, Misto, Ukraine");
    expect(placeLabel("Jabal Qarfan mountain", "Yemen")).toBe("Jabal Qarfan mountain, Yemen");
    expect(placeLabel(null, "Yemen")).toBe("Yemen");
  });
});

describe("news in the last hours", () => {
  const now = Date.parse("2026-10-24T15:07:30Z");

  it("counts back from the last quarter hour", () => {
    expect(reportedSince(24, now)).toBe("2026-10-23T15:00:00.000Z");
    expect(reportedSince(72, now)).toBe("2026-10-21T15:00:00.000Z");
  });

  it("says how long ago a report was", () => {
    expect(describeTimeAgo("2026-10-24T15:00:00Z", now)).toBe("just now");
    expect(describeTimeAgo("2026-10-24T14:15:00Z", now)).toBe("53 min ago");
    expect(describeTimeAgo("2026-10-24T10:00:00Z", now)).toBe("5 h ago");
    expect(describeTimeAgo("2026-10-21T15:00:00Z", now)).toBe("3 days ago");
  });
});

describe("eventCategory", () => {
  it("folds each source's types into the same kinds of violence", () => {
    expect(eventCategory("state_based", true).key).toBe("state");
    expect(eventCategory("battle", true).key).toBe("state");
    expect(eventCategory("non_state", true).key).toBe("non_state");
    expect(eventCategory("one_sided", true).key).toBe("civilians");
    expect(eventCategory("violence_against_civilians", true).key).toBe("civilians");
    expect(eventCategory("mass_violence", true).key).toBe("civilians");
  });

  it("calls every non-violent event a signal, and unknown violence military", () => {
    expect(eventCategory("protest", false).key).toBe("signal");
    expect(eventCategory("riot", false).key).toBe("signal");
    expect(eventCategory("unknown", true).key).toBe("state");
  });
});

describe("kindCategory", () => {
  it("colors an event by its kind of violence, whatever its source's type", () => {
    expect(kindCategory("state_based", true).key).toBe("state");
    expect(kindCategory("non_state", true).key).toBe("non_state");
    expect(kindCategory("one_sided", true).key).toBe("civilians");
  });

  it("says when the kind is unclear, and calls non-violent events signals", () => {
    expect(kindCategory(null, true).key).toBe("unclear");
    expect(kindCategory(null, false).key).toBe("signal");
    expect(kindCategory("state_based", false).key).toBe("signal");
  });

  it("marks a kind read from the sides as likely, but not UCDP's own", () => {
    expect(kindLabel("one_sided", true, "gdelt")).toBe("Likely violence against civilians");
    expect(kindLabel("one_sided", true, "ucdp")).toBe("Violence against civilians");
    expect(kindLabel(null, true, "gdelt")).toBe("Violence, kind unclear");
  });
});

describe("cellCategory", () => {
  const cell = { events: 8, violent: 6, signals: 2, state_based: 1, non_state: 3, one_sided: 1, deaths: 0 };

  it("takes the category most of the area's events fall in", () => {
    expect(cellCategory(cell).key).toBe("non_state");
    // Two violent events with no kind outnumber one of each.
    expect(cellCategory({ ...cell, violent: 5, state_based: 1, non_state: 1, one_sided: 1 }).key).toBe("unclear");
    // Mostly protests and threats, with some violence, reads as signals, as it would up close.
    expect(cellCategory({ ...cell, signals: 4 }).key).toBe("signal");
  });

  it("gives ties to the category listed first", () => {
    expect(cellCategory({ ...cell, violent: 2, state_based: 1, non_state: 1, one_sided: 0, signals: 1 }).key).toBe("state");
    expect(cellCategory({ ...cell, violent: 3, state_based: 0, non_state: 0, one_sided: 0, signals: 3 }).key).toBe("unclear");
  });
});

describe("oneEachStory", () => {
  const event = (id: number, over: Partial<Parameters<typeof oneEachStory>[0][0]> = {}) => ({
    id,
    event_date: "2026-10-18",
    country: "Canada",
    latitude: 53.28,
    longitude: -110.0,
    geo_precision: "exact" as const,
    source_url: `https://news.example/${id}`,
    ...over,
  });

  it("keeps one line per incident however GDELT placed it", () => {
    const kept = oneEachStory([
      event(1), // the base fire, at the town
      event(2, { latitude: 60.1, longitude: -113.6, geo_precision: "country" }), // all of Canada
      event(3, { latitude: 53.7, longitude: -106.0, geo_precision: "admin" }), // the province
      event(4, { latitude: 49.25, longitude: -123.1 }), // Vancouver, 900 km away
      event(5, { event_date: "2026-10-19" }), // the next day
      event(6, { country: "France", latitude: 48.78, longitude: 2.0 }),
    ]);
    expect(kept.map((e) => e.id)).toEqual([1, 4, 5, 6]);
  });

  it("treats a shared article or headline as one story anywhere", () => {
    const kept = oneEachStory([
      event(1, { source_url: "https://a.example/2026/10/23/gunman-kills-one-in-paris-suburb" }),
      event(2, { country: "France", source_url: "https://b.example/news/gunman-kills-one-in-paris-suburb/" }),
      event(3, { country: "France", source_url: "https://a.example/2026/10/23/gunman-kills-one-in-paris-suburb" }),
      event(4, { country: "France", source_url: null }),
    ]);
    expect(kept.map((e) => e.id)).toEqual([1, 4]);
  });
});
