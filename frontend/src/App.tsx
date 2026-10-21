import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { queryString, request } from "./api/client";
import { riskGeoJson, useRiskWeek } from "./api/risk";
import { MAX_POINTS, mapLayerQuery, useEvent, useFacets, useMapLayer, useTasks, useTimeline } from "./api/hooks";
import type { Bbox, CountrySummary, WatchItem } from "./api/types";
import { EventDrawer } from "./components/EventDrawer";
import { FilterBar } from "./components/FilterBar";
import { type MapHandle, MapView } from "./components/MapView";
import { OverviewPanel } from "./components/OverviewPanel";
import { RiskPanel } from "./components/RiskPanel";
import { TasksPanel } from "./components/TasksPanel";
import { TimelineBar } from "./components/TimelineBar";
import { WatchlistPanel } from "./components/WatchlistPanel";
import { useBoard, useBoardGeoJson } from "./board/api";
import { BoardPanel } from "./board/BoardPanel";
import { Welcome } from "./components/Welcome";
import { type DateWindow, addDays, clampWindow, formatDate, intervalFor, shiftWindow, stepFor } from "./lib/dates";
import { formatCount } from "./lib/format";
import { cellSizeForZoom, parseBbox } from "./lib/geo";
import type { Story } from "./lib/stories";
import { type Panel, initialState, reducer, toSearch } from "./state/dashboard";
import { COLORS } from "./theme";

const WELCOME_KEY = "conflict-map:welcome-seen";

export function App() {
  const [state, dispatch] = useReducer(reducer, window.location.search, initialState);
  const facets = useFacets();
  const map = useRef<MapHandle>(null);
  const queryClient = useQueryClient();
  const [welcome, setWelcome] = useState(() => !window.location.search && !seenWelcome());

  const full = useMemo<DateWindow | null>(() => {
    const { first_date, last_date } = facets.data ?? {};
    return first_date && last_date ? { start: first_date, end: last_date } : null;
  }, [facets.data]);
  const domain = state.range && full ? clampWindow(state.range, full) : full;

  // Until the URL or the user picks one, show the most recent year of data.
  useEffect(() => {
    if (full && !state.window) {
      dispatch({ type: "window", window: clampWindow({ start: addDays(full.end, -364), end: full.end }, full) });
    }
  }, [full, state.window]);
  const timeWindow = state.window && domain ? clampWindow(state.window, domain) : null;

  const interval = domain ? intervalFor(domain.start, domain.end) : "month";
  const countingBbox = state.followView ? state.viewBbox : null;
  const cell = cellSizeForZoom(state.camera.zoom);
  const mapScope = { filters: state.filters, window: timeWindow, bbox: pad(state.viewBbox) };
  // On the Risk tab the map shows country risk scores for the window's last week instead.
  const riskMode = state.panel === "risk";
  const [riskCountry, setRiskCountry] = useState<string | null>(null);
  const risk = useRiskWeek(timeWindow?.end ?? null, "score", 300, riskMode && timeWindow !== null);
  const riskLayer = useMemo(() => (riskMode ? riskGeoJson(risk.data) : null), [riskMode, risk.data]);
  const layer = useMapLayer(mapScope, cell, timeWindow !== null && !riskMode);
  const timeline = useTimeline({ filters: state.filters, window: domain, bbox: countingBbox }, interval, domain !== null);
  const selected = useEvent(state.selectedEventId).data;
  // On the Boards tab the open board is drawn over the events.
  const boardId = state.panel === "board" ? state.boardId : null;
  const [boardNode, setBoardNode] = useState<number | null>(null);
  const boardLayer = useBoardGeoJson(boardId, useBoard(boardId).data?.updated_at).data ?? null;
  const openTasks = useTasks().data?.filter((t) => t.status !== "done").length ?? 0;

  // Playback: once the map has the current window's data, wait a beat, then step forward.
  const mapFetching = riskMode ? risk.isFetching : layer.isFetching;
  useEffect(() => {
    if (!state.playing || !timeWindow || !domain || mapFetching) return;
    const next = shiftWindow(timeWindow, stepFor(timeWindow), domain);
    if (next.start === timeWindow.start) {
      dispatch({ type: "play", playing: false });
      return;
    }
    if (!riskMode) void queryClient.prefetchQuery(mapLayerQuery({ ...mapScope, window: next }, cell));
    const timer = setTimeout(() => dispatch({ type: "window", window: next }), 1200 / state.speed);
    return () => clearTimeout(timer);
    // mapScope is rebuilt every render; its parts are listed instead.
  }, [state.playing, state.speed, timeWindow?.start, timeWindow?.end, domain?.start, domain?.end, mapFetching, riskMode, state.filters, state.viewBbox, cell]);

  // Keep the address bar in step, so any view can be shared as a link.
  useEffect(() => {
    const timer = setTimeout(() => window.history.replaceState(null, "", `?${toSearch(state)}`), 300);
    return () => clearTimeout(timer);
  }, [state]);

  const play = (playing: boolean) => {
    if (playing && timeWindow && domain && timeWindow.end >= domain.end) {
      // Start again from the beginning rather than doing nothing at the end.
      dispatch({ type: "window", window: shiftWindow(timeWindow, -1e6, domain) });
    }
    dispatch({ type: "play", playing });
  };

  const showEvent = (event: { id: number; latitude: number; longitude: number }) => {
    dispatch({ type: "select", eventId: event.id });
    map.current?.flyTo(event.longitude, event.latitude);
  };

  const showCountry = (country: string, bbox: Bbox) => {
    dispatch({ type: "filters", filters: { country } });
    map.current?.fitBbox(bbox);
  };

  const openWatchItem = async (item: WatchItem) => {
    const bbox = parseBbox(item.bbox);
    if (bbox) {
      map.current?.fitBbox(bbox);
      return;
    }
    if (!item.country) return;
    dispatch({ type: "filters", filters: { country: item.country } });
    const [found] = await request<CountrySummary[]>(`/countries${queryString({ country: item.country, limit: 1 })}`);
    if (found) map.current?.fitBbox(found.bbox);
  };

  const startStory = (story: Story) => {
    closeWelcome();
    dispatch({ type: "story", range: story.range, windowDays: story.windowDays });
    map.current?.fitBbox(story.bbox);
  };

  const closeWelcome = () => {
    setWelcome(false);
    try {
      localStorage.setItem(WELCOME_KEY, "1");
    } catch {
      // Storage can be unavailable (private windows); the welcome just shows again.
    }
  };

  const setPanel = (panel: Panel) => dispatch({ type: "panel", panel });

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden />
          <h1>Conflict Map</h1>
        </div>
        <FilterBar
          facets={facets.data}
          filters={state.filters}
          onChange={(filters) => dispatch({ type: "filters", filters })}
          onClear={() => dispatch({ type: "clearFilters" })}
        />
        <button className="ghost" onClick={() => setWelcome(true)}>
          Stories &amp; help
        </button>
      </header>

      <aside className="sidebar">
        <nav className="tabs" role="tablist">
          {(
            [
              ["overview", "Overview"],
              ["risk", "Risk"],
              ["board", "Boards"],
              ["watchlist", "Watchlist"],
              ["tasks", openTasks ? `Tasks (${openTasks})` : "Tasks"],
            ] as const
          ).map(([panel, label]) => (
            <button
              key={panel}
              role="tab"
              aria-selected={state.panel === panel}
              className={state.panel === panel ? "is-on" : ""}
              onClick={() => setPanel(panel)}
            >
              {label}
            </button>
          ))}
        </nav>
        {facets.error ? (
          <div className="panel-body">
            <p className="error">
              Can't reach the API ({facets.error.message}). Start the backend with{" "}
              <code>uvicorn app.main:app</code> in <code>backend/</code>, then reload.
            </p>
          </div>
        ) : !timeWindow || !domain ? (
          <div className="panel-body">
            <p className="muted">Loading…</p>
          </div>
        ) : state.panel === "overview" ? (
          <OverviewPanel
            scope={{ filters: state.filters, window: timeWindow, bbox: countingBbox }}
            inView={countingBbox !== null}
            onCountry={showCountry}
            onEvent={showEvent}
          />
        ) : state.panel === "risk" ? (
          <RiskPanel
            week={timeWindow.end}
            onEvent={showEvent}
            selected={riskCountry}
            onSelect={setRiskCountry}
            onCountry={(r) => {
              if (r.longitude !== null && r.latitude !== null) map.current?.flyTo(r.longitude, r.latitude, 5);
            }}
          />
        ) : state.panel === "board" ? (
          <BoardPanel
            boardId={state.boardId}
            selectedNodeId={boardNode}
            mapCenter={state.camera}
            onOpen={(id) => dispatch({ type: "board", boardId: id })}
            onSelectNode={setBoardNode}
            onFocus={(lon, lat) => map.current?.flyTo(lon, lat)}
            onWindow={(w) => dispatch({ type: "window", window: clampWindow(w, domain) })}
          />
        ) : state.panel === "watchlist" ? (
          <WatchlistPanel
            filters={state.filters}
            window={timeWindow}
            domain={domain}
            interval={interval}
            viewBbox={state.viewBbox}
            onOpen={openWatchItem}
          />
        ) : (
          <TasksPanel onEvent={showEvent} onWatchItem={openWatchItem} />
        )}
      </aside>

      <main className="map-area">
        <MapView
          ref={map}
          initialCamera={state.camera}
          layer={layer.data}
          window={timeWindow}
          selected={selected ? { lon: selected.longitude, lat: selected.latitude } : null}
          risk={riskLayer}
          riskSelected={riskCountry}
          board={boardId !== null ? boardLayer : null}
          boardSelected={boardNode}
          onBoardSelect={setBoardNode}
          onMove={(camera, viewBbox) => dispatch({ type: "camera", camera, viewBbox })}
          onSelect={(eventId) => dispatch({ type: "select", eventId })}
          onRiskSelect={setRiskCountry}
        />
        {riskMode ? (
          <>
            <div className="map-status" aria-live="polite">
              {risk.error
                ? `Could not load risk scores: ${risk.error.message}`
                : risk.data
                  ? `Risk scores for the week of ${formatDate(risk.data.week)} · ${formatCount(riskLayer?.features.length ?? 0)} countries`
                  : "Loading risk scores…"}
              {risk.isFetching && <span className="spinner" aria-label="Loading" />}
            </div>
            <RiskLegend />
          </>
        ) : (
          <>
            <MapStatus layer={layer.data} fetching={layer.isFetching} error={layer.error} />
            <Legend grid={layer.data?.mode === "grid"} />
          </>
        )}
        {state.selectedEventId !== null && (
          <EventDrawer
            eventId={state.selectedEventId}
            onClose={() => dispatch({ type: "select", eventId: null })}
            onSelect={showEvent}
            onShowTasks={() => setPanel("tasks")}
          />
        )}
      </main>

      <footer className="timeline-area">
        {domain && full && timeWindow ? (
          <TimelineBar
            buckets={timeline.data?.buckets ?? []}
            interval={timeline.data?.interval ?? interval}
            domain={domain}
            full={full}
            window={timeWindow}
            loading={timeline.isFetching}
            playing={state.playing}
            speed={state.speed}
            followView={state.followView}
            zoomedIn={state.viewBbox !== null}
            onWindow={(w) => dispatch({ type: "window", window: w })}
            onRange={(range) => dispatch({ type: "range", range })}
            onPlay={play}
            onSpeed={(speed) => dispatch({ type: "speed", speed })}
            onFollowView={(followView) => dispatch({ type: "followView", followView })}
          />
        ) : (
          <div className="timeline-placeholder muted">Loading timeline…</div>
        )}
      </footer>

      {welcome && <Welcome facets={facets.data} onStory={startStory} onClose={closeWelcome} />}
    </div>
  );
}

function MapStatus({
  layer,
  fetching,
  error,
}: {
  layer: ReturnType<typeof useMapLayer>["data"];
  fetching: boolean;
  error: Error | null;
}) {
  if (error) return <div className="map-status error">Could not load events: {error.message}</div>;
  if (!layer) return <div className="map-status">Loading events…</div>;
  return (
    <div className="map-status" aria-live="polite">
      {layer.mode === "points" ? (
        <>Showing {formatCount(layer.total)} events</>
      ) : (
        <>
          {formatCount(layer.total)} events, more than the {formatCount(MAX_POINTS)} that can be drawn singly.
          Showing density. Zoom in or shorten the window to see single events.
        </>
      )}
      {fetching && <span className="spinner" aria-label="Loading" />}
    </div>
  );
}

function Legend({ grid }: { grid: boolean }) {
  return (
    <div className="legend map-legend">
      {grid ? (
        <>
          <div className="legend-title">Share of events that are violent</div>
          <div
            className="legend-ramp"
            style={{ background: `linear-gradient(90deg, ${COLORS.signal}, ${COLORS.neutral}, ${COLORS.violence})` }}
          />
          <div className="legend-ends small">
            <span>Signals</span>
            <span>Mixed</span>
            <span>Violence</span>
          </div>
          <div className="small muted">Circle size: number of events</div>
        </>
      ) : (
        <>
          <span>
            <span className="swatch round" style={{ background: COLORS.violence }} /> Violence
          </span>
          <span>
            <span className="swatch round" style={{ background: COLORS.signal }} /> Signal
          </span>
          <span>
            <span className="swatch round hollow" /> Location known to country only
          </span>
          <span className="muted">Size: deaths · faded: earlier in window</span>
        </>
      )}
    </div>
  );
}

function RiskLegend() {
  return (
    <div className="legend map-legend">
      <div className="legend-title">Risk score this week</div>
      <div
        className="legend-ramp"
        style={{ background: "linear-gradient(90deg, #3b3470, #5a4fb0, #8076e0, #aba3f0, #dcd8ff)" }}
      />
      <div className="legend-ends small">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      <span>
        <span className="swatch round alarm-ring" /> Surge alarm
      </span>
      <div className="small muted">Larger and brighter: higher score. Click a country for why.</div>
    </div>
  );
}

function seenWelcome(): boolean {
  try {
    return localStorage.getItem(WELCOME_KEY) === "1";
  } catch {
    return false;
  }
}

/** Widens the view's bbox by a fifth on each side so panning doesn't reveal empty edges. */
function pad(bbox: Bbox | null): Bbox | null {
  if (!bbox) return null;
  const dx = (bbox[2] - bbox[0]) / 5;
  const dy = (bbox[3] - bbox[1]) / 5;
  const r = (v: number) => Math.round(v * 10) / 10;
  return [
    r(Math.max(-180, bbox[0] - dx)),
    r(Math.max(-90, bbox[1] - dy)),
    r(Math.min(180, bbox[2] + dx)),
    r(Math.min(90, bbox[3] + dy)),
  ];
}
