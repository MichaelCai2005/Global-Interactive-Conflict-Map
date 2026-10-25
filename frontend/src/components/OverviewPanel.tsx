import { useCountries, useDeadliest, useSummary } from "../api/hooks";
import type { Scope } from "../api/client";
import type { Bbox, EventOut, Summary } from "../api/types";
import { type DateWindow, daysBetween, describeLength, formatDate, formatRange, previousWindow } from "../lib/dates";
import { eventTypeLabel, formatChange, formatCompact, formatCount, percentChange, placeLabel } from "../lib/format";
import { COLORS } from "../theme";

interface Props {
  scope: Scope & { window: DateWindow };
  inView: boolean;
  onCountry(country: string, bbox: Bbox): void;
  onEvent(event: Pick<EventOut, "id" | "latitude" | "longitude">): void;
}

export function OverviewPanel({ scope, inView, onCountry, onEvent }: Props) {
  const previous = { ...scope, window: previousWindow(scope.window) };
  const current = useSummary(scope);
  const before = useSummary(previous);
  const countries = useCountries(scope, 15);
  const deadliest = useDeadliest(scope, 6, scope.filters.violence !== "signals");
  const length = daysBetween(scope.window.start, scope.window.end) + 1;
  // The newest days often have only news reports, which carry no death counts; then a column
  // of zeros says nothing, so it is dropped.
  const counted = deadliest.data?.items.some((e) => (e.fatalities_best ?? 0) > 0) ?? false;

  return (
    <div className="panel-body">
      <p className="scope-line">
        {formatRange(scope.window)}
        <span className="muted"> · {inView ? "in the map view" : "everywhere"}</span>
        {scope.filters.country && <span className="muted"> · {scope.filters.country}</span>}
      </p>

      <div className="stat-grid">
        <Stat label="Violent events" kind="violent" now={current.data} then={before.data} pick={(s) => s.violent_events} />
        <Stat label="Signal events" kind="signals" now={current.data} then={before.data} pick={(s) => s.signal_events} />
        <Stat label="Deaths" kind="deaths" now={current.data} then={before.data} pick={(s) => s.fatalities} />
      </div>
      <p className="muted small">Change compared with the previous {describeLength(length)}.</p>

      {scope.filters.violence !== "signals" && (
        <section>
          <h3>Deadliest events</h3>
          {!deadliest.data ? (
            <p className="muted small">{deadliest.error ? `Could not load events: ${deadliest.error.message}` : "Loading…"}</p>
          ) : deadliest.data.items.length === 0 ? (
            <p className="muted small">No violent events in this window.</p>
          ) : (
            !counted && <p className="muted small">No deaths recorded in this window yet; newest violent events first.</p>
          )}
          <ol className={`event-list${counted ? "" : " uncounted"}`}>
            {deadliest.data?.items.map((e) => (
              <li key={e.id}>
                <button onClick={() => onEvent(e)}>
                  {counted && <span className="event-deaths num">{formatCompact(e.fatalities_best ?? 0)}</span>}
                  <span className="event-text">
                    <span>{eventTypeLabel(e.event_type)}</span>
                    <span className="muted small">
                      {placeLabel(e.location_name, e.country)} · {formatDate(e.event_date)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h3>Countries</h3>
        {!countries.data ? (
          <p className="muted small">{countries.error ? `Could not load countries: ${countries.error.message}` : "Loading…"}</p>
        ) : (
          countries.data.length === 0 && <p className="muted small">No events in this window.</p>
        )}
        <CountryBars rows={countries.data ?? []} onCountry={onCountry} />
      </section>
    </div>
  );
}

export function Stat({
  label,
  kind,
  now,
  then,
  pick,
}: {
  label: string;
  kind: "violent" | "signals" | "deaths";
  now: Summary | undefined;
  then: Summary | undefined;
  pick(s: Summary): number;
}) {
  const value = now ? pick(now) : null;
  const change = now && then ? percentChange(pick(now), pick(then)) : undefined;
  return (
    <div className="stat">
      <div className="stat-label">
        <span className={`dot dot-${kind}`} aria-hidden /> {label}
      </div>
      <div className="stat-value">{value === null ? "–" : formatCompact(value)}</div>
      {change !== undefined && <Change change={change} />}
    </div>
  );
}

export function Change({ change }: { change: number | null }) {
  // More violence is the worrying direction; the arrow and words carry it, not only color.
  const direction = change === null || change > 0.5 ? "up" : change < -0.5 ? "down" : "flat";
  const arrow = direction === "up" ? "▲" : direction === "down" ? "▼" : "■";
  return (
    <div className={`change change-${direction}`}>
      <span aria-hidden>{arrow}</span> {formatChange(change)}
    </div>
  );
}

export function CountryBars({
  rows,
  onCountry,
}: {
  rows: { country: string; violent_events: number; signal_events: number; fatalities: number; bbox: Bbox }[];
  onCountry: Props["onCountry"];
}) {
  const max = Math.max(1, ...rows.map((r) => r.violent_events + r.signal_events));
  return (
    <>
      {rows.length > 0 && (
        <div className="legend small">
          <span><span className="swatch" style={{ background: COLORS.violence }} /> Violent</span>
          <span><span className="swatch" style={{ background: COLORS.signal }} /> Signals</span>
        </div>
      )}
      <ul className="bars">
        {rows.map((r) => {
          const total = r.violent_events + r.signal_events;
          return (
            <li key={r.country}>
              <button
                onClick={() => onCountry(r.country, r.bbox)}
                title={`${formatCount(r.violent_events)} violent, ${formatCount(r.signal_events)} signals, ${formatCount(r.fatalities)} deaths. Click to filter to ${r.country}.`}
              >
                <span className="bar-label">{r.country}</span>
                <span className="bar-track">
                  <span className="bar" style={{ width: `${(r.violent_events / max) * 100}%`, background: COLORS.violence }} />
                  {r.signal_events > 0 && (
                    <span className="bar" style={{ width: `${(r.signal_events / max) * 100}%`, background: COLORS.signal }} />
                  )}
                </span>
                <span className="num bar-value">{formatCompact(total)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}
