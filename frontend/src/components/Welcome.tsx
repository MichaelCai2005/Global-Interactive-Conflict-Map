import type { Facets } from "../api/types";
import { formatDate } from "../lib/dates";
import { formatCount, SOURCE_DESCRIPTIONS, sourceLabel } from "../lib/format";
import { STORIES, type Story } from "../lib/stories";

interface Props {
  facets: Facets | undefined;
  onTour(): void;
  onNow(): void;
  onStory(story: Story): void;
  /** Brings back Things to try, when it was hidden. */
  onThingsToTry?: () => void;
  onClose(): void;
}

/**
 * The first screen: what this is in two sentences, then one clear way in. Everything else
 * is left for later: Things to try, and the Stories & help button that reopens this.
 */
export function Welcome({ facets, onTour, onNow, onStory, onThingsToTry, onClose }: Props) {
  const total = facets?.sources.reduce((sum, s) => sum + s.count, 0);
  return (
    <div className="welcome-backdrop" onClick={onClose}>
      <div
        className="welcome"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <button className="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <h2 id="welcome-title">How conflicts develop, on a map and a timeline</h2>
        <p>
          {total ? `${formatCount(total)} events` : "Events"}
          {facets?.first_date && facets.last_date && ` from ${facets.first_date.slice(0, 4)} to ${facets.last_date.slice(0, 4)}`}.{" "}
          <span className="dot dot-violent" aria-hidden /> <strong>Violence</strong> is what happened;{" "}
          <span className="dot dot-signals" aria-hidden /> <strong>signals</strong> are the protests, threats and
          troop movements around it.
        </p>

        <div className="welcome-start">
          <button className="story now-story primary" onClick={onNow} disabled={!facets?.last_date}>
            <span className="story-title">
              <span className="live-dot" aria-hidden /> See what's happening now
            </span>
            <span className="small">
              The latest week{facets?.last_date && `, to ${formatDate(facets.last_date)}`}: the news, the deadliest
              fighting, and where risk is rising.
            </span>
          </button>
          <button className="tour-start" onClick={onTour}>
            New here? Take the one-minute tour
          </button>
        </div>

        <h3>Or replay a past conflict</h3>
        <div className="stories">
          {STORIES.map((s) => (
            <button key={s.id} className="story" title={s.summary} onClick={() => onStory(s)}>
              <span className="story-title">{s.title}</span>
              <span className="muted small">{s.period}</span>
            </button>
          ))}
        </div>

        <div className="welcome-foot">
          <button className="link-button" onClick={onClose}>
            Explore on my own
          </button>
          {onThingsToTry && (
            <button className="link-button" onClick={onThingsToTry}>
              Show Things to try
            </button>
          )}
        </div>

        <details className="welcome-sources">
          <summary className="small muted">Where the data comes from</summary>
          <p className="small">Merged from three sources and cleaned of duplicates.</p>
          <ul className="sources">
            {facets?.sources.map((s) => (
              <li key={s.value}>
                <strong>{sourceLabel(s.value)}</strong> <span className="muted">{formatCount(s.count)}</span>
                <div className="muted small">{SOURCE_DESCRIPTIONS[s.value]}</div>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}
