import { useState } from "react";
import { useCountries, useSummary, useViolentEvents } from "../api/hooks";
import { useRiskWeek } from "../api/risk";
import type { Bbox, EventOut, Facets } from "../api/types";
import { type DateWindow, addDays, formatDate, formatRange, previousWindow } from "../lib/dates";
import { eventTypeLabel, formatCompact, placeLabel, plural, SOURCE_UPDATES, sourceLabel } from "../lib/format";
import {
  deathsThrough,
  describeAge,
  describeTimeAgo,
  headlineFromUrl,
  latestWindow,
  oneEachStory,
  reportedSince,
  todayIso,
} from "../lib/now";
import type { Filters } from "../state/dashboard";
import { CountryBars, Stat } from "./OverviewPanel";

interface Props {
  facets: Facets;
  filters: Filters;
  /** The map view when the timeline follows it, else null for everywhere. */
  bbox: Bbox | null;
  /** The map's time window, to offer moving it to the newest week. */
  window: DateWindow;
  onShowLatest(days: number): void;
  onEvent(event: Pick<EventOut, "id" | "latitude" | "longitude">): void;
  onCountry(country: string, bbox: Bbox): void;
  onRisk(iso3: string, lon: number | null, lat: number | null): void;
}

const WEEK = 7;
/**
 * GDELT event types for the news list: armed fighting (CAMEO 19) and mass violence (20).
 * Assault (18) is left out because in the news it is mostly crime.
 */
const NEWS_TYPES = ["fight", "mass_violence"];
/** The "Today" choices: news GDELT first published in the last this many hours. */
const TODAY_HOURS = [24, 48, 72];

/**
 * What is happening now: the newest week of data, whatever the timeline shows. Each section
 * names its source, because the newest week holds only GDELT's machine-coded news events;
 * UCDP's counted deaths arrive a month at a time, weeks later.
 */
export function NowPanel({ facets, filters, bbox, window, onShowLatest, onEvent, onCountry, onRisk }: Props) {
  const last = facets.last_date!;
  const week = latestWindow(last, WEEK);
  const scope = { filters, window: week, bbox };
  const current = useSummary(scope);
  const before = useSummary({ ...scope, window: previousWindow(week) });
  const violence = filters.violence !== "signals";
  const newsScope = { ...scope, filters: { ...filters, types: filters.types.length ? filters.types : NEWS_TYPES } };
  // GDELT codes one story many times over, so take extra and keep each story once.
  const reported = useViolentEvents(newsScope, "reports", 50, violence);
  const news = oneEachStory(reported.data?.items ?? []).slice(0, 6);
  const deathsEnd = deathsThrough(facets.sources, filters.sources);
  const deathsWindow = deathsEnd ? latestWindow(deathsEnd, 30) : null;
  const deadliest = useViolentEvents({ ...scope, window: deathsWindow }, "fatalities", 5, violence && deathsWindow !== null);
  // The API moves rising risk back to the newest week with every death counted.
  const rising = useRiskWeek(last, "rise", 6);
  const risers = rising.data?.regions ?? [];
  const countries = useCountries(scope, 8);
  const onMap = window.start === week.start && window.end === week.end;
  const today = todayIso();

  const [hours, setHours] = useState(24);
  const since = reportedSince(hours);
  // GDELT sometimes dates a new article's event from an old one it mentions, so events dated
  // before the window are left out too.
  const recent = { start: addDays(since.slice(0, 10), -1), end: today };
  const todayScope = { filters, window: recent, bbox, reportedSince: since };
  const todayCounts = useSummary(todayScope);
  const todayReported = useViolentEvents({ ...todayScope, filters: newsScope.filters }, "reports", 50, violence);
  const todayNews = oneEachStory(todayReported.data?.items ?? []).slice(0, 6);
  const gdeltAllowed = filters.sources.length === 0 || filters.sources.includes("gdelt");

  return (
    <div className="panel-body now-panel">
      <p className="scope-line">
        <span className="live-dot" aria-hidden /> Latest week: {formatRange(week)}
        <span className="muted"> · {bbox ? "in the map view" : "everywhere"}</span>
        {filters.country && <span className="muted"> · {filters.country}</span>}
      </p>
      {!onMap && (
        <button className="primary small wide" onClick={() => onShowLatest(WEEK)}>
          Show the latest week on the map
        </button>
      )}

      {gdeltAllowed && (
        <section className="today">
          <div className="today-head">
            <h3>News in the last {hours} hours</h3>
            <div className="segmented small" role="radiogroup" aria-label="Hours of news">
              {TODAY_HOURS.map((h) => (
                <button key={h} role="radio" aria-checked={hours === h} className={hours === h ? "is-on" : ""} onClick={() => setHours(h)}>
                  {h}h
                </button>
              ))}
            </div>
          </div>
          <p className="unconfirmed small">
            <strong>Unconfirmed news reports.</strong> GDELT codes these by machine from articles within 15 minutes of
            publication. Nobody has checked them, and no deaths are counted yet.
          </p>
          {todayCounts.data && (
            <p className="small">
              {plural(todayCounts.data.violent_events, "violent event")} and{" "}
              {plural(todayCounts.data.signal_events, "signal event")} first reported since{" "}
              {new Date(since).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}
              {bbox ? " in the map view" : ""}.
            </p>
          )}
          {violence && todayReported.data?.items.length === 0 && (
            <p className="muted small">
              No fighting first reported in these {hours} hours. If this stays empty, GDELT's 15-minute feed may not be
              loading.
            </p>
          )}
          {violence && (
            <EventList events={todayNews} value={(e) => e.report_count} unit="reports" headlines reported onEvent={onEvent} />
          )}
          <button className="small wide" onClick={() => onShowLatest(hours / 24 + 1)}>
            Show the last {hours / 24 + 1} days on the map
          </button>
        </section>
      )}

      <ul className="freshness">
        {facets.sources.map((s) => (
          <li key={s.value}>
            <strong>{sourceLabel(s.value)}</strong>
            {s.last_date && (
              <span>
                {" "}
                to {formatDate(s.last_date)} <span className="muted">({describeAge(s.last_date, today)})</span>
              </span>
            )}
            {SOURCE_UPDATES[s.value] && <div className="muted small">{SOURCE_UPDATES[s.value]}</div>}
          </li>
        ))}
      </ul>

      <div className="stat-grid">
        <Stat label="Violent events" kind="violent" now={current.data} then={before.data} pick={(s) => s.violent_events} />
        <Stat label="Signal events" kind="signals" now={current.data} then={before.data} pick={(s) => s.signal_events} />
        <Stat label="Deaths" kind="deaths" now={current.data} then={before.data} pick={(s) => s.fatalities} />
      </div>
      <p className="muted small">
        Change compared with the week before.
        {deathsEnd && deathsEnd < week.start && " No deaths are counted yet for this week."}
      </p>

      {violence && (
        <section>
          <h3>Fighting in the news this week</h3>
          <p className="muted small">
            Most reported first (GDELT). Coded by machine from the news and not yet confirmed, so read the article.
          </p>
          {reported.data?.items.length === 0 && <p className="muted small">No fighting reported this week.</p>}
          <EventList events={news} value={(e) => e.report_count} unit="reports" headlines onEvent={onEvent} />
        </section>
      )}

      {violence && deathsWindow && (
        <section>
          <h3>Deadliest in the newest month of death counts</h3>
          <p className="muted small">{formatRange(deathsWindow)}, the latest that UCDP has coded.</p>
          {deadliest.data?.items.length === 0 && <p className="muted small">No deaths recorded in these 30 days.</p>}
          <EventList events={deadliest.data?.items ?? []} value={(e) => e.fatalities_best ?? 0} unit="deaths" onEvent={onEvent} />
        </section>
      )}

      {rising.data && risers.length > 0 && (
        <section>
          <h3>Risk rising most</h3>
          <p className="muted small">
            Week of {formatDate(rising.data.week)}, the newest with counted deaths. Click for why.
          </p>
          <ol className="rise-list">
            {risers.map((r) => (
              <li key={r.iso3}>
                <button onClick={() => onRisk(r.iso3, r.longitude, r.latitude)}>
                  <span>{r.name}</span>
                  <span className="num" title="Risk score, 0-100">{Math.round(r.score)}</span>
                  <span className="num change change-up" title="Change on the week before">
                    <span aria-hidden>▲</span> {Math.round(r.change ?? 0)}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h3>Busiest countries this week</h3>
        {countries.data?.length === 0 && <p className="muted small">No events this week.</p>}
        <CountryBars rows={countries.data ?? []} onCountry={onCountry} />
      </section>
    </div>
  );
}

function EventList({
  events,
  value,
  unit,
  headlines = false,
  reported = false,
  onEvent,
}: {
  events: EventOut[];
  value(event: EventOut): number;
  unit: string;
  /** Title each event by its article's headline and link to it. */
  headlines?: boolean;
  /** Say when GDELT first published each event instead of its date. */
  reported?: boolean;
  onEvent: Props["onEvent"];
}) {
  return (
    <ol className="event-list">
      {events.map((e) => {
        const headline = headlines && e.source_url ? headlineFromUrl(e.source_url) : null;
        return (
          <li key={e.id}>
            <button onClick={() => onEvent(e)} title={`${plural(value(e), unit.replace(/s$/, ""))}. Click to show it on the map.`}>
              <span className="event-deaths num">{formatCompact(value(e))}</span>
              <span className="event-text">
                <span>{headline ?? eventTypeLabel(e.event_type)}</span>
                <span className="muted small">
                  {placeLabel(e.location_name, e.country)} ·{" "}
                  {reported && e.first_reported_at ? `reported ${describeTimeAgo(e.first_reported_at)}` : formatDate(e.event_date)} ·{" "}
                  {sourceLabel(e.source)}
                </span>
              </span>
            </button>
            {headlines && e.source_url && (
              <a className="event-article small" href={e.source_url} target="_blank" rel="noreferrer noopener">
                Read the article ({hostOf(e.source_url)})
              </a>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "link";
  }
}
