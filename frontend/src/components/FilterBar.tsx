import { useEffect, useRef, useState } from "react";
import type { Facets } from "../api/types";
import { CATEGORIES, eventCategory } from "../lib/categories";
import { SOURCE_DESCRIPTIONS, eventTypeLabel, formatCount, sourceLabel } from "../lib/format";
import { EMPTY_FILTERS, type Filters, type Violence } from "../state/dashboard";

interface Props {
  facets: Facets | undefined;
  filters: Filters;
  onChange(filters: Partial<Filters>): void;
  onClear(): void;
}

const CLASSES: { value: Violence; label: string; title: string }[] = [
  { value: "all", label: "All events", title: "Violence and the signals around it" },
  { value: "violent", label: "Violence", title: "Fighting, attacks and other violent events" },
  {
    value: "signals",
    label: "Signals",
    title: "Non-violent events that can come before violence: protests, threats, troop movements",
  },
];

export function FilterBar({ facets, filters, onChange, onClear }: Props) {
  const active = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <div className="filter-bar" role="toolbar" aria-label="Filters" data-tour="filters">
      <div className="segmented" role="radiogroup" aria-label="Event class">
        {CLASSES.map((c) => (
          <button
            key={c.value}
            role="radio"
            aria-checked={filters.violence === c.value}
            className={filters.violence === c.value ? "is-on" : ""}
            title={c.title}
            onClick={() => onChange({ violence: c.value, types: [] })}
          >
            {c.value !== "all" && <span className={`dot dot-${c.value}`} aria-hidden />}
            {c.label}
          </button>
        ))}
      </div>

      <div className="chips" aria-label="Sources">
        {facets?.sources.map((s) => (
          <button
            key={s.value}
            className={`chip${filters.sources.includes(s.value) ? " is-on" : ""}`}
            aria-pressed={filters.sources.includes(s.value)}
            title={`${SOURCE_DESCRIPTIONS[s.value] ?? ""} (${formatCount(s.count)} events)`}
            onClick={() => onChange({ sources: toggle(filters.sources, s.value) })}
          >
            {sourceLabel(s.value)}
          </button>
        ))}
      </div>

      <TypePicker facets={facets} filters={filters} onChange={onChange} />
      <CountryPicker facets={facets} value={filters.country} onChange={(country) => onChange({ country })} />

      {active && (
        <button className="link-button" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}

function TypePicker({ facets, filters, onChange }: Omit<Props, "onClear">) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  // The same type name can appear as violent in one source and not another; merge by name.
  const types = new Map<string, { count: number; violent: boolean }>();
  for (const t of facets?.event_types ?? []) {
    const seen = types.get(t.value);
    types.set(t.value, { count: (seen?.count ?? 0) + t.count, violent: seen?.violent ?? t.is_violent });
  }
  // Grouped by the categories the map colors events by.
  const groups = CATEGORIES.filter(
    (g) => filters.violence === "all" || (filters.violence === "violent") === g.violent,
  ).filter((g) => [...types].some(([value, t]) => eventCategory(value, t.violent).key === g.key));

  const label =
    filters.types.length === 0
      ? "All event types"
      : filters.types.length === 1
        ? eventTypeLabel(filters.types[0]!)
        : `${filters.types.length} event types`;

  return (
    <div className="picker" ref={ref}>
      <button className={`chip chip-select${filters.types.length ? " is-on" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        {label} <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className="popover type-popover" role="dialog" aria-label="Event types">
          {groups.map((g) => (
            <fieldset key={g.key}>
              <legend title={g.description}>
                <span className="dot" style={{ background: g.color }} aria-hidden /> {g.label}
              </legend>
              {[...types.entries()]
                .filter(([value, t]) => eventCategory(value, t.violent).key === g.key)
                .map(([value, t]) => (
                  <label key={value} className="check">
                    <input
                      type="checkbox"
                      checked={filters.types.includes(value)}
                      onChange={() =>
                        onChange({
                          types: filters.types.includes(value)
                            ? filters.types.filter((v) => v !== value)
                            : [...filters.types, value],
                        })
                      }
                    />
                    <span>{eventTypeLabel(value)}</span>
                    <span className="num muted">{formatCount(t.count)}</span>
                  </label>
                ))}
            </fieldset>
          ))}
          {filters.types.length > 0 && (
            <button className="link-button" onClick={() => onChange({ types: [] })}>
              Show all types
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function CountryPicker({
  facets,
  value,
  onChange,
}: {
  facets: Facets | undefined;
  value: string | null;
  onChange(country: string | null): void;
}) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const names = facets?.countries.map((c) => c.value) ?? [];

  const commit = (next: string) => {
    const match = names.find((n) => n.toLowerCase() === next.trim().toLowerCase());
    if (match) onChange(match);
    else if (!next.trim()) onChange(null);
  };

  return (
    <div className={`country-picker${value ? " is-on" : ""}`}>
      <input
        list="country-options"
        placeholder="Any country"
        aria-label="Country"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          // Picking from the list fires a change with the full name.
          if (names.includes(e.target.value)) onChange(e.target.value);
        }}
        onBlur={() => commit(text)}
        onKeyDown={(e) => e.key === "Enter" && commit(text)}
      />
      {value && (
        <button className="clear" aria-label="Clear country" onClick={() => onChange(null)}>
          ×
        </button>
      )}
      <datalist id="country-options">
        {names.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
    </div>
  );
}
