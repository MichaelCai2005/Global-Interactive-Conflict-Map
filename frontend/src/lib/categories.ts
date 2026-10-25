// Event categories: UCDP's three kinds of violence, which every source's violent events
// are sorted into (events.conflict_type, see backend/app/conflict_type.py), so the map
// colors UCDP, ACLED and GDELT alike. For ACLED and GDELT the kind is inferred from the
// sides the source names; violence whose sides do not settle it is "unclear".
//
// No source labels an event "genocide": that is a legal finding about intent, made long
// after the killing. Massacres and other mass killing of civilians are counted as
// violence against civilians (UCDP's "one-sided violence").

import type { CellProps } from "../api/types";

export type CategoryKey = "state" | "non_state" | "civilians" | "unclear" | "signal";
export type ConflictType = "state_based" | "non_state" | "one_sided";

export interface Category {
  key: CategoryKey;
  label: string;
  description: string;
  violent: boolean;
  /** Map color, for the dark map surface; see theme.ts. */
  color: string;
}

// Orange, aqua and violet clear the colorblind and normal-vision floors for every pair on
// the map surface (#14171b); a fourth hue cannot, so signals take a recessive grey that
// still separates from all three. Only three hues fit, so the map uses them for violence,
// and violence of unclear kind takes a light grey, far brighter than the signals' grey.
export const CATEGORIES: Category[] = [
  {
    key: "state",
    label: "Military conflict",
    description: "Fighting involving a government's forces, against another state or rebels; battles and bombing",
    violent: true,
    color: "#d95926",
  },
  {
    key: "non_state",
    label: "Non-state armed groups",
    description: "Armed groups fighting each other with no government side: militias, cartels, rival rebels",
    violent: true,
    color: "#199e70",
  },
  {
    key: "civilians",
    label: "Violence against civilians",
    description:
      "A government or armed group killing unarmed people: massacres and mass atrocities, the violence genocide is made of",
    violent: true,
    color: "#9085e9",
  },
  {
    key: "unclear",
    label: "Violence, kind unclear",
    description: "Reported violence whose sides the source does not name clearly enough to tell which kind it is",
    violent: true,
    color: "#b4afa5",
  },
  {
    key: "signal",
    label: "Signals",
    description: "Non-violent events that can come before violence: protests, threats, troop movements",
    violent: false,
    color: "#6b6964",
  },
];

const BY_KEY = Object.fromEntries(CATEGORIES.map((c) => [c.key, c])) as Record<CategoryKey, Category>;

/** Each kind of violence's category. */
export const KIND_CATEGORY: Record<ConflictType, Exclude<CategoryKey, "unclear" | "signal">> = {
  state_based: "state",
  non_state: "non_state",
  one_sided: "civilians",
};

/** The category of one event, from its kind of violence (conflict_type). */
export function kindCategory(kind: string | null | undefined, violent: boolean): Category {
  if (!violent) return BY_KEY.signal;
  return BY_KEY[KIND_CATEGORY[kind as ConflictType] ?? "unclear"];
}

/** An event's category as words, "Likely ..." when the kind was read from the sides ACLED
 *  or GDELT name rather than decided by UCDP. */
export function kindLabel(kind: string | null | undefined, violent: boolean, source: string): string {
  const { label } = kindCategory(kind, violent);
  return violent && kind && source !== "ucdp" ? `Likely ${label.toLowerCase()}` : label;
}

export const INFERRED_KIND_NOTE = "Judged from how the source names the two sides; UCDP has not confirmed it.";

/** The category a grid cell of the map is colored by: the one most of its events fall
 *  in, ties going to the category listed first. */
export function cellCategory(p: CellProps): Category {
  const kinds = Object.keys(KIND_CATEGORY) as ConflictType[];
  const counts: [CategoryKey, number][] = [
    ...kinds.map((kind): [CategoryKey, number] => [KIND_CATEGORY[kind], p[kind]]),
    ["unclear", p.violent - kinds.reduce((n, kind) => n + p[kind], 0)],
    ["signal", p.signals],
  ];
  return BY_KEY[counts.reduce((best, c) => (c[1] > best[1] ? c : best))[0]];
}

/** The category an event type mostly falls in, for grouping types in the filter. A type
 *  is not an event: GDELT fighting can be any kind, which only its sides tell. */
export const CATEGORY_TYPES: Record<Exclude<CategoryKey, "unclear" | "signal">, string[]> = {
  state: ["state_based", "battle", "explosion_remote_violence", "fight"],
  non_state: ["non_state"],
  civilians: ["one_sided", "violence_against_civilians", "mass_violence", "assault"],
};

const TYPE_CATEGORY = new Map<string, CategoryKey>(
  Object.entries(CATEGORY_TYPES).flatMap(([key, types]) => types.map((t) => [t, key as CategoryKey])),
);

export function eventCategory(type: string, violent: boolean): Category {
  if (!violent) return BY_KEY.signal;
  return BY_KEY[TYPE_CATEGORY.get(type) ?? "state"];
}

// Deaths run on a log scale: one hue, dim at one death and bright past a thousand, so a
// massacre outshines a skirmish. Events with no recorded deaths stay grey.
export const DEATH_STOPS: [deaths: number, color: string][] = [
  [1, "#b3421b"],
  [10, "#d8582e"],
  [100, "#f98662"],
  [1000, "#ffc3ae"],
];
export const NO_DEATHS_COLOR = BY_KEY.signal.color;

export type ColorBy = "type" | "deaths";
