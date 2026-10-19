import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RiskExplanation, RiskSeries, RiskWeek } from "../api/risk";
import { riskGeoJson, weekOf } from "../api/risk";
import { RiskPanel, signed } from "./RiskPanel";

const points = { history: 43.7, surge: 20.5, spread: 15.9, signal: 0 };

const WEEK: RiskWeek = {
  week: "2023-10-09",
  previous_week: "2023-10-02",
  first_week: "1989-01-02",
  last_week: "2026-10-12",
  provisional: false,
  regions: [
    {
      iso3: "ISR",
      name: "Israel",
      latitude: 31.5,
      longitude: 34.8,
      score: 80.1,
      change: 14.2,
      points,
      trend: null,
      surge_alarm: true,
      provisional: false,
    },
  ],
};

const SERIES: RiskSeries = {
  iso3: "ISR",
  name: "Israel",
  neighbours: ["LBN", "SYR"],
  points: ["2023-09-25", "2023-10-02", "2023-10-09"].map((week, i) => ({
    week,
    score: 60 + i * 10,
    change: i ? 10 : null,
    points,
    trend: null,
    surge_alarm: i === 2,
    provisional: false,
    violent_events: 5 + i * 60,
    deaths: 10 + i * 600,
    gdelt_events: 0,
  })),
};

const WHY: RiskExplanation = {
  iso3: "ISR",
  name: "Israel",
  week: "2023-10-09",
  previous_week: "2023-10-02",
  score: 80.1,
  previous_score: 65.9,
  change: 14.2,
  trend: null,
  surge_alarm: true,
  provisional: false,
  summary: "Score 80 (+14 on the week before). Surge rose most (+11 points).",
  components: [
    { component: "surge", points: 20.5, previous_points: 9.1, change: 11.4, explanation: "136 UCDP violent events against a usual 1.2 a week." },
    { component: "history", points: 43.7, previous_points: 40.9, change: 2.8, explanation: "1,285 deaths this week." },
    { component: "spread", points: 15.9, previous_points: 15.8, change: 0.1, explanation: "Neighbours average 350 decayed deaths." },
    { component: "signal", points: 0, previous_points: 0, change: 0, explanation: "Too little GDELT coverage for a baseline." },
  ],
  events: [
    {
      id: 7,
      source: "ucdp",
      source_event_id: "7",
      event_date: "2023-10-09",
      end_date: null,
      event_type: "state_based",
      is_violent: true,
      country: "Israel",
      admin1: null,
      location_name: "Jabaliyah refugee camp",
      latitude: 31.53,
      longitude: 34.48,
      geo_precision: "exact",
      actor1: null,
      actor2: null,
      fatalities_best: 73,
      fatalities_low: null,
      fatalities_high: null,
      report_count: 1,
      tone: null,
      source_url: null,
      conflict_id: null,
      duplicate_of_id: null,
      attributes: {},
    },
  ],
  neighbours: [{ iso3: "SYR", name: "Syria", score: 58, history: 1662 }],
};

function mockApi() {
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.includes("/weeks/") ? WHY : url.startsWith("/api/risk/") ? SERIES : WEEK;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPanel(props: Partial<Parameters<typeof RiskPanel>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RiskPanel week="2023-10-11" onEvent={() => {}} {...props} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RiskPanel", () => {
  it("ranks countries for the timeline's week and explains one when opened", async () => {
    const fetchMock = mockApi();
    const onEvent = vi.fn();
    const onCountry = vi.fn();
    renderPanel({ onEvent, onCountry });

    expect(await screen.findByText("Week of 9 Oct 2023")).toBeTruthy();
    expect(fetchMock.mock.calls[0]![0]).toContain("week=2023-10-11");
    expect(screen.getByText("▲ Surge alarm")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /Israel/ }));
    expect(onCountry).toHaveBeenCalledWith(expect.objectContaining({ iso3: "ISR" }));
    expect(await screen.findByText(/Surge rose most/)).toBeTruthy();
    expect(screen.getByText("136 UCDP violent events against a usual 1.2 a week.")).toBeTruthy();
    expect(screen.getByRole("img", { name: /latest 80/ })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /Jabaliyah/ }));
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));

    await userEvent.click(screen.getByRole("button", { name: /All countries/ }));
    expect(await screen.findByRole("radio", { name: "Rising" })).toBeTruthy();
  });
});

describe("RiskPanel with a controlled selection", () => {
  it("opens the country it is given and reports selection changes", async () => {
    mockApi();
    const onSelect = vi.fn();
    const { rerender } = renderPanel({ selected: "ISR", onSelect });

    expect(await screen.findByText(/Surge rose most/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /All countries/ }));
    expect(onSelect).toHaveBeenCalledWith(null);
    // The parent still says ISR, so the country stays open until it changes the prop.
    expect(screen.getByRole("button", { name: /All countries/ })).toBeTruthy();

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <RiskPanel week="2023-10-11" onEvent={() => {}} selected={null} onSelect={onSelect} />
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Israel/ }));
    expect(onSelect).toHaveBeenLastCalledWith("ISR");
  });
});

describe("risk helpers", () => {
  it("never shows a change as -0", () => {
    expect(signed(-0.01, 1)).toBe("0.0");
    expect(signed(-0.3, 0)).toBe("0");
    expect(signed(0.04, 1)).toBe("0.0");
    expect(signed(2.84, 1)).toBe("+2.8");
    expect(signed(-11.4, 1)).toBe("-11.4");
  });

  it("finds the Monday a date's week starts on", () => {
    expect(weekOf("2023-10-09")).toBe("2023-10-09");
    expect(weekOf("2023-10-15")).toBe("2023-10-09");
    expect(weekOf("2023-10-16")).toBe("2023-10-16");
  });

  it("turns a week of scores into map points", () => {
    const layer = riskGeoJson(WEEK);
    expect(layer.features).toHaveLength(1);
    expect(layer.features[0]!.properties).toMatchObject({ iso3: "ISR", score: 80, change: 14, alarm: true });
  });
});
