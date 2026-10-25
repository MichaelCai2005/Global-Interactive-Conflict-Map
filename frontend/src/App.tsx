import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { type Layout, type LayoutChangedMeta, useGroupRef } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useMe } from "./api/account";
import { queryString, request } from "./api/client";
import { riskGeoJson, useRiskWeek } from "./api/risk";
import { MAX_POINTS, mapLayerQuery, useEvent, useFacets, useMapLayer, useTasks, useTimeline } from "./api/hooks";
import type { Bbox, CountrySummary, WatchItem } from "./api/types";
import { AccountMenu } from "./components/AccountMenu";
import { type AuthMode, AuthDialog, SignInPrompt } from "./components/AuthDialog";
import { EventDrawer } from "./components/EventDrawer";
import { FilterBar } from "./components/FilterBar";
import { type MapHandle, MapView, NEW_DAYS } from "./components/MapView";
import { OverviewPanel } from "./components/OverviewPanel";
import { RiskPanel } from "./components/RiskPanel";
import { SavedPanel } from "./components/SavedPanel";
import { TasksPanel } from "./components/TasksPanel";
import { TimelineBar } from "./components/TimelineBar";
import { WatchlistPanel } from "./components/WatchlistPanel";
import { type BoardNode, useBoard, useBoardGeoJson } from "./board/api";
import { BoardCanvas, type BoardSelection, type CanvasHandle } from "./board/BoardCanvas";
import { BoardPanel } from "./board/BoardPanel";
import { Tour } from "./components/Tour";
import { Welcome } from "./components/Welcome";
import { NowPanel } from "./components/NowPanel";
import { CloseButton, PaneToggles, Workspace, usePanes } from "./components/Workspace";
import { type DateWindow, clampWindow, daysBetween, formatDate, intervalFor, shiftWindow, stepFor } from "./lib/dates";
import { CATEGORIES, type ColorBy, DEATH_STOPS, NO_DEATHS_COLOR } from "./lib/categories";
import { formatCount } from "./lib/format";
import { cellSizeForZoom, parseBbox } from "./lib/geo";
import { latestWindow } from "./lib/now";
import type { Story } from "./lib/stories";
import { type Panel, initialState, reducer, toSearch } from "./state/dashboard";
import { COLORS } from "./theme";

const WELCOME_KEY = "conflict-map:welcome-seen";
const COLOR_BY_KEY = "conflict-map:color-by";
const WORLD: Bbox = [-150, -50, 170, 70];

type BoardView = "board" | "split" | "map";

export function App() {
  const [state, dispatch] = useReducer(reducer, window.location.search, initialState);
  const facets = useFacets();
  const map = useRef<MapHandle>(null);
  const queryClient = useQueryClient();
  const [welcome, setWelcome] = useState(() => !window.location.search && !seenWelcome());
  // While the tour runs, the tab it began on, to go back to afterwards.
  const [tour, setTour] = useState<Panel | null>(null);
  // Who is signed in. A visitor to the public site must sign in to keep anything.
  const me = useMe().data;
  const canSave = me !== undefined && me.workspace !== null;
  const [auth, setAuth] = useState<AuthMode | null>(null);

  const full = useMemo<DateWindow | null>(() => {
    const { first_date, last_date } = facets.data ?? {};
    return first_date && last_date ? { start: first_date, end: last_date } : null;
  }, [facets.data]);
  const domain = state.range && full ? clampWindow(state.range, full) : full;

  // Until the URL or the user picks one, show the newest week of data, on a timeline of the
  // past year so that week has room to be seen.
  useEffect(() => {
    if (full && !state.window) {
      if (!state.range) dispatch({ type: "range", range: clampWindow(latestWindow(full.end, 365), full) });
      dispatch({ type: "window", window: clampWindow(latestWindow(full.end, 7), full) });
    }
  }, [full, state.window, state.range]);
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
  const openBoard = useBoard(boardId).data;
  const [boardSelection, setBoardSelection] = useState<BoardSelection>(null);
  const boardNode = boardSelection?.type === "node" ? boardSelection.id : null;
  const boardLayer = useBoardGeoJson(boardId, openBoard?.updated_at).data ?? null;
  // With a board open, the main area shows its canvas, the map, or both side by side.
  const [boardView, setBoardView] = useState<BoardView>("board");
  const [colorBy, setColorBy] = useState<ColorBy>(savedColorBy);
  const chooseColorBy = (value: ColorBy) => {
    setColorBy(value);
    try {
      localStorage.setItem(COLOR_BY_KEY, value);
    } catch {
      // Private windows can refuse storage; the choice then lasts this visit only.
    }
  };
  const view: BoardView = boardId === null ? "map" : boardView;
  const canvas = useRef<CanvasHandle>(null);
  useEffect(() => setBoardSelection(null), [boardId]);
  const panes = usePanes();
  // Board and map share the main area. The view buttons close one or the other (the map
  // stays mounted, so it keeps its state), the split comes back as last dragged, and
  // dragging the edge between them shut picks the matching view.
  const split = useGroupRef();
  const lastSplit = useRef<Layout>({ "split-board": 55, "split-map": 45 });
  useEffect(() => {
    if (boardId === null) return;
    split.current?.setLayout(
      view === "board"
        ? { "split-board": 100, "split-map": 0 }
        : view === "map"
          ? { "split-board": 0, "split-map": 100 }
          : lastSplit.current,
    );
  }, [view, boardId, split]);
  const onSplitChanged = (layout: Layout, meta: LayoutChangedMeta) => {
    if (boardId === null) return;
    if (layout["split-board"]! > 0 && layout["split-map"]! > 0) lastSplit.current = layout;
    if (meta.isUserInteraction) {
      setBoardView(layout["split-map"] === 0 ? "board" : layout["split-board"] === 0 ? "map" : "split");
    }
  };
  const openTasks = useTasks(canSave).data?.filter((t) => t.status !== "done").length ?? 0;

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

  /** Moves the window to end on the newest data, keeping its length unless given one. */
  const showLatest = (days?: number) => {
    if (!full || !timeWindow) return;
    const next = clampWindow(latestWindow(full.end, days ?? daysBetween(timeWindow.start, timeWindow.end) + 1), full);
    // A zoomed timeline that stops short of the newest data stretches to take it in.
    if (state.range && (state.range.end < next.end || state.range.start > next.start)) {
      dispatch({
        type: "range",
        range: { start: state.range.start < next.start ? state.range.start : next.start, end: full.end },
      });
    }
    dispatch({ type: "play", playing: false });
    dispatch({ type: "window", window: next });
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

  const startNow = () => {
    closeWelcome();
    dispatch({ type: "panel", panel: "now" });
    showLatest(7);
    map.current?.fitBbox(WORLD);
  };

  const startStory = (story: Story) => {
    closeWelcome();
    dispatch({ type: "story", range: story.range, windowDays: story.windowDays });
    map.current?.fitBbox(story.bbox);
  };

  const startTour = () => {
    closeWelcome();
    // The tour points at the side panel and timeline, so open them if they were closed.
    if (panes.wide) {
      panes.sidebar.toggle(true);
      panes.timeline.toggle(true);
    }
    dispatch({ type: "select", eventId: null });
    setTour(state.panel);
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

  const focusCard = (node: BoardNode) => {
    if (view !== "map") canvas.current?.centerOn(node.id);
    if (view !== "board" && node.latitude !== null && node.longitude !== null) map.current?.flyTo(node.longitude, node.latitude);
  };
  const showOnMap = (node: BoardNode) => {
    if (view === "board") setBoardView("split");
    setBoardSelection({ type: "node", id: node.id });
    // Let the map take its new size before flying.
    setTimeout(() => {
      if (node.latitude !== null && node.longitude !== null) map.current?.flyTo(node.longitude, node.latitude);
    }, 50);
  };

  const restoreView = (search: string) => {
    const { camera } = initialState(search);
    dispatch({ type: "restore", search });
    map.current?.flyTo(camera.lon, camera.lat, camera.zoom);
  };
  const signInPrompt = (what: string) => <SignInPrompt what={what} onSignIn={setAuth} />;

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
        <PaneToggles panes={panes} />
        <button className="ghost" data-tour="help" onClick={() => setWelcome(true)}>
          Stories &amp; help
        </button>
        <AccountMenu me={me} onSignIn={setAuth} onSaved={() => setPanel("saved")} />
      </header>

      <Workspace
        panes={panes}
        sidebar={
          <aside className="sidebar" data-tour="sidebar">
            <div className="sidebar-head">
              <nav className="tabs" role="tablist">
                {(
                  [
                    ["now", "Now"],
                    ["overview", "Overview"],
                    ["risk", "Risk"],
                    ["board", "Boards"],
                    ["watchlist", "Watchlist"],
                    ["tasks", openTasks ? `Tasks (${openTasks})` : "Tasks"],
                    ["saved", "Saved"],
                  ] as const
                ).map(([panel, label]) => (
                  <button
                    key={panel}
                    data-tour={`tab-${panel}`}
                    role="tab"
                    aria-selected={state.panel === panel}
                    className={state.panel === panel ? "is-on" : ""}
                    onClick={() => setPanel(panel)}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {panes.wide && <CloseButton label="Close side panel" onClick={() => panes.sidebar.toggle(false)} />}
            </div>
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
            ) : state.panel === "now" && facets.data ? (
              <NowPanel
                facets={facets.data}
                filters={state.filters}
                bbox={countingBbox}
                window={timeWindow}
                onShowLatest={showLatest}
                onEvent={showEvent}
                onCountry={showCountry}
                onRisk={(iso3, lon, lat) => {
                  setRiskCountry(iso3);
                  setPanel("risk");
                  if (lon !== null && lat !== null) map.current?.flyTo(lon, lat, 5);
                }}
              />
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
                selection={boardSelection}
                mapCenter={state.camera}
                onOpen={(id) => dispatch({ type: "board", boardId: id })}
                onSelect={setBoardSelection}
                onFocus={focusCard}
                onShowOnMap={showOnMap}
                onWindow={(w) => dispatch({ type: "window", window: clampWindow(w, domain) })}
              />
            ) : (state.panel === "watchlist" || state.panel === "tasks" || state.panel === "saved") && !canSave ? (
              me ? (
                signInPrompt(
                  state.panel === "watchlist"
                    ? "a watchlist of places"
                    : state.panel === "tasks"
                      ? "a list of follow-up tasks"
                      : "saved map views and searches",
                )
              ) : (
                <div className="panel-body">
                  <p className="muted">Loading…</p>
                </div>
              )
            ) : state.panel === "saved" ? (
              <SavedPanel
                filters={state.filters}
                window={timeWindow}
                query={toSearch({ ...state, panel: "overview", playing: false })}
                onRestore={restoreView}
                onBoard={(id) => dispatch({ type: "board", boardId: id })}
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
        }
        map={
          <main className={`map-area view-${view}${boardId !== null ? " board-open" : ""}`}>
            {boardId !== null && (
              <div className="view-switch segmented small" role="tablist" aria-label="Show">
                {(
                  [
                    ["board", "Board"],
                    ["split", "Board + map"],
                    ["map", "Map"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    role="tab"
                    aria-selected={view === value}
                    className={view === value ? "is-on" : ""}
                    onClick={() => setBoardView(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            <ResizablePanelGroup id="board-split" orientation="horizontal" groupRef={split} onLayoutChanged={onSplitChanged}>
              {boardId !== null && (
                <ResizablePanel id="split-board" className="pane" defaultSize="55%" minSize="20%" collapsible>
                  {openBoard && view !== "map" && (
                    <div className="board-pane">
                      <BoardCanvas ref={canvas} board={openBoard} selection={boardSelection} onSelect={setBoardSelection} />
                    </div>
                  )}
                </ResizablePanel>
              )}
              {boardId !== null && <ResizableHandle withHandle className="workspace-handle" />}
              <ResizablePanel
                id="split-map"
                className="pane"
                minSize="20%"
                collapsible={boardId !== null}
                style={{ overflow: "hidden" }}
              >
                <div className="map-pane" data-tour="map">
                  <MapView
                    ref={map}
                    initialCamera={state.camera}
                    layer={layer.data}
                    colorBy={colorBy}
                    window={timeWindow}
                    latest={full?.end}
                    selected={selected ? { lon: selected.longitude, lat: selected.latitude } : null}
                    risk={riskLayer}
                    riskSelected={riskCountry}
                    board={boardId !== null ? boardLayer : null}
                    boardSelected={boardNode}
                    onBoardSelect={(id) => {
                      setBoardSelection({ type: "node", id });
                      canvas.current?.centerOn(id);
                    }}
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
                      <Legend
                        colorBy={colorBy}
                        onColorBy={chooseColorBy}
                        grid={layer.data?.mode === "grid"}
                        ringed={boardId === null && !!full && !!timeWindow && daysBetween(timeWindow.end, full.end) < NEW_DAYS}
                      />
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
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </main>
        }
        timeline={
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
                onLatest={() => showLatest()}
                onClose={panes.wide ? () => panes.timeline.toggle(false) : undefined}
              />
            ) : (
              <div className="timeline-placeholder muted">Loading timeline…</div>
            )}
          </footer>
        }
      />

      {welcome && (
        <Welcome facets={facets.data} onTour={startTour} onNow={startNow} onStory={startStory} onClose={closeWelcome} />
      )}
      {tour && <Tour startPanel={tour} onPanel={setPanel} onClose={() => setTour(null)} />}
      {auth && <AuthDialog mode={auth} signupsOpen={me?.signups_open ?? true} onClose={() => setAuth(null)} />}
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

function Legend({
  colorBy,
  onColorBy,
  grid,
  ringed,
}: {
  colorBy: ColorBy;
  onColorBy(value: ColorBy): void;
  grid: boolean;
  ringed: boolean;
}) {
  return (
    <div className="legend map-legend" data-tour="legend">
      <div className="segmented small" role="radiogroup" aria-label="Color events by">
        {(
          [
            ["type", "Type"],
            ["deaths", "Deaths"],
          ] as const
        ).map(([value, label]) => (
          <button key={value} role="radio" aria-checked={colorBy === value} className={colorBy === value ? "is-on" : ""} onClick={() => onColorBy(value)}>
            {label}
          </button>
        ))}
      </div>
      {colorBy === "deaths" ? (
        <>
          <div className="legend-title">{grid ? "Deaths in each area" : "Deaths per event"}</div>
          <div
            className="legend-ramp"
            style={{ background: `linear-gradient(90deg, ${DEATH_STOPS.map(([, c]) => c).join(", ")})` }}
          />
          <div className="legend-ends small">
            {DEATH_STOPS.map(([n], i) => (
              <span key={n}>
                {formatCount(n)}
                {i === DEATH_STOPS.length - 1 && "+"}
              </span>
            ))}
          </div>
          <span title="GDELT news reports and most signals carry no death count">
            <span className="swatch round" style={{ background: NO_DEATHS_COLOR }} /> None recorded
          </span>
        </>
      ) : grid ? (
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
        </>
      ) : (
        CATEGORIES.map((c) => (
          <span key={c.key} title={c.description}>
            <span className="swatch round" style={{ background: c.color }} /> {c.label}
          </span>
        ))
      )}
      {grid ? (
        <div className="small muted">Circle size: number of events</div>
      ) : (
        <>
          <span>
            <span className="swatch round hollow" /> Location known to country only
          </span>
          {ringed && (
            <span>
              <span className="swatch round ringed" /> Newest {NEW_DAYS} days of data
            </span>
          )}
          <span className="muted">Size: deaths · faded: earlier in window</span>
        </>
      )}
    </div>
  );
}

function RiskLegend() {
  return (
    <div className="legend map-legend" data-tour="legend">
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

function savedColorBy(): ColorBy {
  try {
    return localStorage.getItem(COLOR_BY_KEY) === "deaths" ? "deaths" : "type";
  } catch {
    return "type";
  }
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
