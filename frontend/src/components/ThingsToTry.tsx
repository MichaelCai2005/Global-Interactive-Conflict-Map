import { Check, ChevronDown, ChevronUp, X } from "lucide-react";
import type { Discovery, DiscoveryItem } from "../lib/discover";
import { useStoredFlag } from "../lib/storage";

interface Props {
  items: DiscoveryItem[];
  done: ReadonlySet<Discovery>;
  /** Points at the control an item is about. */
  onShow(item: DiscoveryItem): void;
  onHide(): void;
}

/**
 * A small card over the map suggesting the next thing to try, so newcomers meet the app one
 * feature at a time. It can open into the whole list, and be hidden for good.
 */
export function ThingsToTry({ items, done, onShow, onHide }: Props) {
  const [expanded, setExpanded] = useStoredFlag("conflict-map:things-expanded");
  const count = items.filter((i) => done.has(i.key)).length;
  const next = items.find((i) => !done.has(i.key));

  return (
    <section className={`things${expanded ? " is-expanded" : ""}`} aria-label="Things to try" data-tour="discover">
      <div className="things-head">
        <h3>Things to try</h3>
        <span className="small muted num">
          {count} of {items.length}
        </span>
        <span className="spacer" />
        <button
          className="icon-button"
          aria-expanded={expanded}
          aria-label={expanded ? "Show just the next one" : "Show them all"}
          title={expanded ? "Show just the next one" : "Show them all"}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <ChevronDown /> : <ChevronUp />}
        </button>
        <button className="icon-button" aria-label="Hide things to try" title="Hide (Stories & help brings it back)" onClick={onHide}>
          <X />
        </button>
      </div>
      <div className="things-progress" aria-hidden>
        <span style={{ width: `${(count / items.length) * 100}%` }} />
      </div>
      {expanded ? (
        <ol className="things-list">
          {items.map((item) => {
            const isDone = done.has(item.key);
            return (
              <li key={item.key} className={isDone ? "is-done" : item === next ? "is-next" : ""}>
                <span className="things-check" aria-label={isDone ? "Done" : "Not yet"}>
                  {isDone && <Check />}
                </span>
                <span className="things-title">{item.title}</span>
                {!isDone && (
                  <button className="link-button small" onClick={() => onShow(item)}>
                    Show me
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      ) : next ? (
        <div className="things-next">
          <strong>{next.title}</strong>
          <p className="small">{next.hint}</p>
          <button className="primary small" onClick={() => onShow(next)}>
            Show me
          </button>
        </div>
      ) : null}
      {!next && (
        <div className="things-next">
          <p className="small">You've tried everything. Each tab has more to find as you go.</p>
          <button className="small" onClick={onHide}>
            Done
          </button>
        </div>
      )}
    </section>
  );
}
