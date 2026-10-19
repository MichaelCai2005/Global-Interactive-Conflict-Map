import { useEffect, useRef, useState } from "react";
import type { EventOut } from "../api/types";
import {
  RISK_COMPONENTS,
  type RiskPoint,
  type RiskRegion,
  type RiskSort,
  type RiskTrend,
  useRiskExplanation,
  useRiskSeries,
  useRiskWeek,
  weekOf,
} from "../api/risk";
import { addDays, formatDate } from "../lib/dates";
import { eventTypeLabel, formatCompact, formatCount, sourceLabel } from "../lib/format";
import { COLORS } from "../theme";
import "./RiskPanel.css";

interface Props {
  /** The point on the timeline to score, usually the end of the map's time window. */
  week: string;
  onEvent(event: Pick<EventOut, "id" | "latitude" | "longitude">): void;
  /** Called when a country is opened from the list, e.g. to fly the map there. */
  onCountry?(region: RiskRegion): void;
  /** The open country (ISO3), when the parent controls it, e.g. from a map click. */
  selected?: string | null;
  /** Called with the ISO3 of the country opened, or null when going back to the list. */
  onSelect?(iso3: string | null): void;
}

const SORTS: [RiskSort, string][] = [
  ["score", "Highest"],
  ["rise", "Rising"],
  ["fall", "Falling"],
];
const SPANS: [number, string][] = [
  [26, "6 months"],
  [52, "1 year"],
  [156, "3 years"],
];
const TREND_TEXT: Record<RiskTrend, string> = {
  new: "New hot spot",
  intensifying: "Intensifying",
  diminishing: "Diminishing",
  persistent: "Persistent",
};
const LIST_LENGTH = 15;

/** Weekly conflict risk by country at the timeline's current week, and why it changed. */
export function RiskPanel({ week, onEvent, onCountry, selected: selectedProp, onSelect }: Props) {
  const [sort, setSort] = useState<RiskSort>("score");
  const [showAll, setShowAll] = useState(false);
  const [ownSelected, setOwnSelected] = useState<string | null>(null);
  const selected = selectedProp !== undefined ? selectedProp : ownSelected;
  const setSelected = (iso3: string | null) => {
    if (selectedProp === undefined) setOwnSelected(iso3);
    onSelect?.(iso3);
  };
  const risk = useRiskWeek(week, sort);
  const data = risk.data;
  const rows = data?.regions ?? [];

  const open = (region: RiskRegion) => {
    setSelected(region.iso3);
    onCountry?.(region);
  };

  return (
    <div className="panel-body risk-panel">
      <p className="scope-line">
        {data ? `Week of ${formatDate(data.week)}` : "Risk"}
        {data && data.week !== weekOf(week) && (
          <span className="muted"> · nearest scored week to {formatDate(week)}</span>
        )}
      </p>
      {risk.isError && <p className="error small">{risk.error.message}</p>}
      {data?.provisional && (
        <p className="risk-note small">
          Provisional: UCDP and ACLED do not cover this week yet, so History only decays and Surge
          is left out.
        </p>
      )}

      {selected && data ? (
        <CountryRisk
          key={selected}
          iso3={selected}
          week={data.week}
          firstWeek={data.first_week}
          onBack={() => setSelected(null)}
          onEvent={onEvent}
        />
      ) : (
        <>
          <div className="risk-toolbar">
            <div className="chips" role="radiogroup" aria-label="Sort countries">
              {SORTS.map(([value, label]) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={sort === value}
                  className={`chip ${sort === value ? "is-on" : ""}`}
                  onClick={() => setSort(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <Legend />
          {data && rows.length === 0 && <p className="muted small">No country has a score this week.</p>}
          <ol className="risk-list">
            {(showAll ? rows : rows.slice(0, LIST_LENGTH)).map((r) => (
              <li key={r.iso3}>
                <RegionRow region={r} onOpen={() => open(r)} />
              </li>
            ))}
          </ol>
          {rows.length > LIST_LENGTH && (
            <button className="risk-more small" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show fewer" : `Show all ${rows.length} countries`}
            </button>
          )}
          <p className="muted small risk-method">
            Each score adds four parts: History (deaths, fading with a 26-week half-life, up to 40
            points), Surge (violence above the country's own baseline), Spread (violence in
            neighbouring countries) and Signal (hostile shifts in GDELT news coverage), up to 20 each.
            A part with no data that week is left out and the rest are scaled to 100.
          </p>
        </>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="legend small risk-legend">
      {RISK_COMPONENTS.map((c) => (
        <span key={c.key} title={c.question}>
          <span className="swatch" style={{ background: c.color }} /> {c.label}
        </span>
      ))}
    </div>
  );
}

function RegionRow({ region, onOpen }: { region: RiskRegion; onOpen(): void }) {
  const title = RISK_COMPONENTS.map((c) => `${c.label} ${region.points[c.key].toFixed(0)}`).join(", ");
  return (
    <button className="risk-row" onClick={onOpen} title={`${title}. Click for what changed.`}>
      <span className="risk-name">
        <span className="bar-label">{region.name}</span>
        <span className="risk-tags small">
          {region.trend && <span className={`risk-tag risk-tag-${region.trend}`}>{TREND_TEXT[region.trend]}</span>}
          {region.surge_alarm && <span className="risk-tag risk-tag-alarm">▲ Surge alarm</span>}
        </span>
      </span>
      <ScoreBar points={region.points} />
      <span className="num risk-score">{region.score.toFixed(0)}</span>
      <ScoreChange change={region.change} />
    </button>
  );
}

/** The score as one 0-100 track, split into its components. */
function ScoreBar({ points }: { points: RiskPoint["points"] }) {
  return (
    <span className="risk-track" aria-hidden>
      {RISK_COMPONENTS.map((c) =>
        points[c.key] >= 0.5 ? (
          <span key={c.key} className="risk-seg" style={{ width: `${points[c.key]}%`, background: c.color }} />
        ) : null,
      )}
    </span>
  );
}

function ScoreChange({ change }: { change: number | null }) {
  if (change === null) return <span className="change small">–</span>;
  const rounded = Math.round(change);
  // A rising score is the worrying direction; the arrow and sign carry it, not only color.
  const direction = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
  const arrow = direction === "up" ? "▲" : direction === "down" ? "▼" : "■";
  return (
    <span className={`change change-${direction} num risk-change`}>
      <span aria-hidden>{arrow}</span> {rounded > 0 ? "+" : ""}
      {rounded}
    </span>
  );
}

function CountryRisk({
  iso3,
  week,
  firstWeek,
  onBack,
  onEvent,
}: {
  iso3: string;
  week: string;
  firstWeek: string;
  onBack(): void;
  onEvent: Props["onEvent"];
}) {
  const [span, setSpan] = useState(52);
  // The week explained below: the timeline's week until a week on the chart is picked.
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => setPicked(null), [week]);
  const start = maxDate(addDays(week, -7 * (span - 1)), firstWeek);
  const series = useRiskSeries(iso3, start, week);
  const shown = picked ?? week;
  const why = useRiskExplanation(iso3, shown);
  const name = series.data?.name ?? why.data?.name ?? iso3;

  return (
    <section className="risk-country">
      <div className="risk-country-head">
        <button className="small" onClick={onBack}>
          ← All countries
        </button>
        <div className="chips" role="radiogroup" aria-label="Chart span">
          {SPANS.map(([weeks, label]) => (
            <button
              key={weeks}
              role="radio"
              aria-checked={span === weeks}
              className={`chip ${span === weeks ? "is-on" : ""}`}
              onClick={() => setSpan(weeks)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <h2 className="risk-title">{name}</h2>
      <Legend />
      {series.data && (
        <RiskChart points={series.data.points} current={week} picked={shown} onPick={setPicked} />
      )}
      <p className="muted small">Click a week on the chart to see what changed in it.</p>

      {why.isError && <p className="error small">{why.error.message}</p>}
      {why.data && (
        <>
          <h3>
            Week of {formatDate(why.data.week)}
            {picked && picked !== week && (
              <button className="chip small" onClick={() => setPicked(null)}>
                Back to timeline week
              </button>
            )}
          </h3>
          <div className="risk-headline">
            <span className="risk-big num">{why.data.score.toFixed(0)}</span>
            <ScoreChange change={why.data.change} />
            {why.data.trend && (
              <span className={`risk-tag risk-tag-${why.data.trend} small`}>{TREND_TEXT[why.data.trend]}</span>
            )}
            {why.data.surge_alarm && <span className="risk-tag risk-tag-alarm small">▲ Surge alarm</span>}
          </div>
          <p className="risk-summary">{why.data.summary}</p>

          <table className="risk-table small">
            <thead>
              <tr>
                <th scope="col">Part</th>
                <th scope="col" className="num">Points</th>
                <th scope="col" className="num">Change</th>
              </tr>
            </thead>
            <tbody>
              {why.data.components.map((c) => {
                const meta = RISK_COMPONENTS.find((m) => m.key === c.component)!;
                return (
                  <tr key={c.component}>
                    <th scope="row">
                      <span className="swatch" style={{ background: meta.color }} /> {meta.label}
                      <div className="muted risk-why">{c.explanation}</div>
                    </th>
                    <td className="num">{c.points.toFixed(1)}</td>
                    <td className="num">{c.change === null ? "–" : signed(c.change, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <h3>Events that week</h3>
          {why.data.events.length === 0 && <p className="muted small">No events recorded this week.</p>}
          <ol className="event-list">
            {why.data.events.map((e) => (
              <li key={e.id}>
                <button onClick={() => onEvent(e)} title="Show on the map">
                  <span className="event-deaths num">
                    {e.is_violent ? formatCompact(e.fatalities_best ?? 0) : "–"}
                  </span>
                  <span className="event-text">
                    <span>
                      {eventTypeLabel(e.event_type)} <span className="muted small">· {sourceLabel(e.source)}</span>
                    </span>
                    <span className="muted small">
                      {[e.location_name, e.admin1].filter(Boolean).join(", ") || e.country} · {formatDate(e.event_date)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {why.data.events.length > 0 && <p className="muted small">Numbers are deaths (best estimate).</p>}

          {why.data.neighbours.length > 0 && (
            <>
              <h3>Neighbours</h3>
              <p className="small">
                {why.data.neighbours.map((n, i) => (
                  <span key={n.iso3}>
                    {i > 0 && ", "}
                    {n.name} <span className="muted num">({n.score.toFixed(0)})</span>
                  </span>
                ))}
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}

const W = 320;
const H = 120;

/** The score over time, stacked by component, with the timeline's week marked. */
function RiskChart({
  points,
  current,
  picked,
  onPick,
}: {
  points: RiskPoint[];
  current: string;
  picked: string;
  onPick(week: string): void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (points.length === 0) return <p className="muted small">No scores in this span.</p>;

  const n = points.length;
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => H - (v / 100) * H;
  const index = (week: string) => points.findIndex((p) => p.week === week);

  // Cumulative tops of each band, bottom to top.
  const bands = RISK_COMPONENTS.map((c, k) => {
    const below = points.map((p) => RISK_COMPONENTS.slice(0, k).reduce((s, m) => s + p.points[m.key], 0));
    const above = points.map((p, i) => below[i]! + p.points[c.key]);
    const top = above.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const bottom = below.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).reverse();
    return { ...c, area: `M${top.join("L")}L${bottom.join("L")}Z`, line: `M${top.join("L")}` };
  });

  const pointAt = (clientX: number) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return null;
    const i = Math.round(((clientX - box.left) / box.width) * (n - 1));
    return Math.min(Math.max(i, 0), n - 1);
  };
  const marker = (week: string, className: string) => {
    const i = index(week);
    return i < 0 ? null : <line className={className} x1={x(i)} x2={x(i)} y1={0} y2={H} vectorEffect="non-scaling-stroke" />;
  };
  const hovered = hover === null ? null : points[hover]!;

  return (
    <div className="risk-chart">
      <div className="risk-y small muted" aria-hidden>
        <span>100</span>
        <span>50</span>
        <span>0</span>
      </div>
      <div
        ref={ref}
        className="risk-plot"
        onMouseMove={(e) => setHover(pointAt(e.clientX))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const i = pointAt(e.clientX);
          if (i !== null) onPick(points[i]!.week);
        }}
      >
        <svg
          width="100%"
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Risk score from ${formatDate(points[0]!.week)} to ${formatDate(points[n - 1]!.week)}, latest ${points[n - 1]!.score.toFixed(0)}`}
        >
          {[25, 50, 75].map((v) => (
            <line key={v} x1={0} x2={W} y1={y(v)} y2={y(v)} stroke={COLORS.grid} vectorEffect="non-scaling-stroke" />
          ))}
          {bands.map((b) => (
            <path key={b.key} d={b.area} fill={b.color} />
          ))}
          {/* A thin surface-colored edge on each band keeps neighbouring fills apart. */}
          {bands.map((b) => (
            <path key={b.key} d={b.line} fill="none" stroke={COLORS.surface} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          ))}
          <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} stroke={COLORS.muted} vectorEffect="non-scaling-stroke" />
          {picked !== current && marker(picked, "risk-marker-picked")}
          {marker(current, "risk-marker-current")}
          {hover !== null && <line className="risk-marker-hover" x1={x(hover)} x2={x(hover)} y1={0} y2={H} vectorEffect="non-scaling-stroke" />}
        </svg>
        {hovered && (
          <div className={`risk-tooltip small ${hover! > n / 2 ? "is-left" : ""}`} style={{ left: `${(x(hover!) / W) * 100}%` }}>
            <div>
              <strong>Week of {formatDate(hovered.week)}</strong>
            </div>
            <div className="risk-tooltip-score">
              Score <span className="num">{hovered.score.toFixed(0)}</span>
              {hovered.change !== null && (
                <span className="muted num"> ({signed(hovered.change, 0)})</span>
              )}
            </div>
            {[...RISK_COMPONENTS].reverse().map((c) => (
              <div key={c.key} className="risk-tooltip-row">
                <span>
                  <span className="swatch" style={{ background: c.color }} /> {c.label}
                </span>
                <span className="num">{hovered.points[c.key].toFixed(0)}</span>
              </div>
            ))}
            <div className="muted">
              {formatCount(hovered.violent_events)} violent events, {formatCount(hovered.deaths)} deaths
            </div>
          </div>
        )}
      </div>
      <div className="risk-x small muted" aria-hidden>
        <span>{formatDate(points[0]!.week)}</span>
        <span>{formatDate(points[n - 1]!.week)}</span>
      </div>
    </div>
  );
}

/** A change with its sign; one that rounds to zero shows as 0, never -0. */
export function signed(value: number, digits: number): string {
  const text = value.toFixed(digits);
  if (Number(text) === 0) return (0).toFixed(digits);
  return value > 0 ? `+${text}` : text;
}

function maxDate(a: string, b: string): string {
  return a > b ? a : b;
}
