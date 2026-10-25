import { useState } from "react";
import { useEvent, useTaskMutations, useTasks } from "../api/hooks";
import type { EventDetail, EventOut } from "../api/types";
import { INFERRED_KIND_NOTE, kindCategory, kindLabel } from "../lib/categories";
import { formatDate } from "../lib/dates";
import { eventTypeLabel, formatCount, plural, sourceLabel } from "../lib/format";
import { describeTimeAgo, headlineFromUrl } from "../lib/now";

interface Props {
  eventId: number;
  onClose(): void;
  onSelect(event: Pick<EventOut, "id" | "latitude" | "longitude">): void;
  onShowTasks(): void;
}

const PRECISION: Record<EventOut["geo_precision"], string> = {
  exact: "Exact place",
  admin: "Region (admin area)",
  country: "Country only",
};

export function EventDrawer({ eventId, onClose, onSelect, onShowTasks }: Props) {
  const { data: event, isLoading, error } = useEvent(eventId);
  return (
    <aside className="drawer" aria-label="Event details">
      <button className="drawer-close" onClick={onClose} aria-label="Close details">
        ×
      </button>
      {isLoading && <p className="muted">Loading event…</p>}
      {error && <p className="error">Could not load this event: {error.message}</p>}
      {event && <Detail event={event} onSelect={onSelect} onShowTasks={onShowTasks} />}
    </aside>
  );
}

function Detail({
  event,
  onSelect,
  onShowTasks,
}: { event: EventDetail } & Pick<Props, "onSelect" | "onShowTasks">) {
  // GDELT's admin1 is a code ("SU52"), and its place name already ends in region and country.
  const location = event.location_name ?? "";
  const region = event.source !== "gdelt" && event.admin1 && !location.includes(event.admin1) ? event.admin1 : null;
  const country = event.country && !location.endsWith(event.country) ? event.country : null;
  const place = [event.location_name, region, country].filter(Boolean);
  const deaths =
    event.fatalities_best === null
      ? null
      : event.fatalities_low !== null &&
          event.fatalities_high !== null &&
          event.fatalities_low !== event.fatalities_high
        ? `${formatCount(event.fatalities_best)} (estimates ${formatCount(event.fatalities_low)}–${formatCount(event.fatalities_high)})`
        : formatCount(event.fatalities_best);
  const actors = [event.actor1, event.actor2].filter(Boolean);
  const extras = Object.entries(event.attributes).filter(
    ([, v]) => v !== null && v !== "" && typeof v !== "object",
  );

  const category = kindCategory(event.conflict_type, event.is_violent);
  const label = kindLabel(event.conflict_type, event.is_violent, event.source);

  return (
    <>
      <div className={`drawer-kind kind-${event.is_violent ? "violent" : "signals"}`} title={label === category.label ? category.description : `${category.description}. ${INFERRED_KIND_NOTE}`}>
        <span className="dot" style={{ background: category.color }} aria-hidden />
        {label}
      </div>
      <h2>{eventTypeLabel(event.event_type)}</h2>
      <p className="drawer-sub">
        {formatDate(event.event_date)}
        {event.end_date && event.end_date !== event.event_date && ` – ${formatDate(event.end_date)}`}
        {place.length > 0 && ` · ${place.join(", ")}`}
      </p>
      {event.source === "gdelt" && (
        <p className="unconfirmed small">
          <strong>Unconfirmed news report.</strong> GDELT codes events by machine from news articles; nobody has checked
          this one. Read the articles before relying on it.
        </p>
      )}

      <dl className="facts">
        {deaths !== null && (
          <>
            <dt>Deaths</dt>
            <dd>{deaths}</dd>
          </>
        )}
        {actors.length > 0 && (
          <>
            <dt>Actors</dt>
            <dd>{actors.join(" vs ")}</dd>
          </>
        )}
        <dt>Location</dt>
        <dd>
          {PRECISION[event.geo_precision]} · {event.latitude.toFixed(3)}, {event.longitude.toFixed(3)}
        </dd>
        <dt>Source</dt>
        <dd>
          {sourceLabel(event.source)} #{event.source_event_id}
          {event.report_count > 1 && ` · ${formatCount(event.report_count)} reports`}
          {event.source_url && (
            <>
              {" · "}
              <a href={event.source_url} target="_blank" rel="noreferrer noopener">
                article
              </a>
            </>
          )}
        </dd>
        {event.first_reported_at && (
          <>
            <dt>First reported</dt>
            <dd>
              {new Date(event.first_reported_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}{" "}
              <span className="muted">({describeTimeAgo(event.first_reported_at)})</span>
            </dd>
          </>
        )}
        {event.tone !== null && (
          <>
            <dt>News tone</dt>
            <dd>{event.tone.toFixed(1)} (negative is hostile)</dd>
          </>
        )}
        {event.conflict_id && (
          <>
            <dt>Conflict</dt>
            <dd>{event.conflict_id}</dd>
          </>
        )}
      </dl>

      {event.sources.length > 0 && <Articles sources={event.sources} total={event.source_count} />}

      {event.duplicate_of && (
        <section className="drawer-section">
          <h3>Also reported by</h3>
          <p className="muted small">
            A higher-priority source has this incident; the map shows that record instead.
          </p>
          <LinkedList links={[event.duplicate_of]} onSelect={onSelect} />
        </section>
      )}
      {event.duplicates.length > 0 && (
        <section className="drawer-section">
          <h3>Matching reports from other sources</h3>
          <LinkedList links={event.duplicates} onSelect={onSelect} />
        </section>
      )}

      {extras.length > 0 && (
        <details className="drawer-section">
          <summary>Source fields ({extras.length})</summary>
          <dl className="facts small">
            {extras.map(([k, v]) => (
              <div key={k} className="fact-row">
                <dt>{k.replace(/_/g, " ")}</dt>
                <dd>{String(v)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      <EventTasks event={event} onShowTasks={onShowTasks} />
    </>
  );
}

function Articles({ sources, total }: { sources: EventDetail["sources"]; total: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? sources : sources.slice(0, 8);
  return (
    <section className="drawer-section">
      <h3>News articles ({formatCount(total)})</h3>
      <p className="muted small">Every article GDELT matched to this event, earliest first.</p>
      <ul className="articles">
        {shown.map((s) => (
          <li key={s.url}>
            <a href={s.url} target="_blank" rel="noreferrer noopener" title={s.url}>
              {headlineFromUrl(s.url) ?? s.url}
            </a>
            <span className="muted small">
              {s.source_name ?? "unknown site"}
              {s.first_seen_at &&
                ` · ${new Date(s.first_seen_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`}
            </span>
          </li>
        ))}
        {sources.length > shown.length && (
          <li>
            <button className="link-button small" onClick={() => setAll(true)}>
              Show all {sources.length}
            </button>
          </li>
        )}
      </ul>
      {total > sources.length && <p className="muted small">Showing the first {sources.length}.</p>}
    </section>
  );
}

function LinkedList({
  links,
  onSelect,
}: {
  links: EventDetail["duplicates"];
  onSelect: Props["onSelect"];
}) {
  const [all, setAll] = useState(false);
  const shown = all ? links : links.slice(0, 8);
  return (
    <ul className="linked">
      {shown.map((l) => (
        <li key={l.event.id}>
          <button className="link-button" onClick={() => onSelect(l.event)}>
            {sourceLabel(l.event.source)} · {eventTypeLabel(l.event.event_type)}
          </button>
          <span className="muted small">
            {" "}
            {l.distance_km.toFixed(1)} km, {l.day_gap === 0 ? "same day" : `${plural(l.day_gap, "day")} apart`}
          </span>
        </li>
      ))}
      {links.length > shown.length && (
        <li>
          <button className="link-button small" onClick={() => setAll(true)}>
            Show all {links.length}
          </button>
        </li>
      )}
    </ul>
  );
}

function EventTasks({ event, onShowTasks }: { event: EventDetail; onShowTasks(): void }) {
  const tasks = useTasks().data?.filter((t) => t.event_id === event.id) ?? [];
  const { create } = useTaskMutations();
  const [title, setTitle] = useState("");
  const suggested = `Review ${eventTypeLabel(event.event_type).toLowerCase()} in ${
    event.location_name ?? event.country ?? "this area"
  }, ${formatDate(event.event_date)}`;

  return (
    <section className="drawer-section">
      <h3>Analyst tasks</h3>
      {tasks.length > 0 && (
        <ul className="linked">
          {tasks.map((t) => (
            <li key={t.id}>
              <span className={`status status-${t.status}`}>{t.status.replace("_", " ")}</span> {t.title}
            </li>
          ))}
        </ul>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate({ title: title.trim() || suggested, event_id: event.id }, { onSuccess: () => setTitle("") });
        }}
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={suggested}
          aria-label="New task title"
        />
        <button type="submit" disabled={create.isPending}>
          Add task
        </button>
      </form>
      {create.isSuccess && (
        <button className="link-button small" onClick={onShowTasks}>
          Task added. Open the task list
        </button>
      )}
      {create.error && <p className="error small">{create.error.message}</p>}
    </section>
  );
}
