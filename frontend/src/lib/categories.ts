// Event categories: the sources' own event types folded into a few kinds of violence that
// read the same across UCDP, ACLED and GDELT. The map colors events by these.
//
// No source labels an event "genocide": that is a legal finding about intent, made long
// after the killing. Massacres and other mass killing of civilians are counted as
// violence against civilians (UCDP's "one-sided violence").

export type CategoryKey = "state" | "non_state" | "civilians" | "signal";

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
// still separates from all three. Only three hues fit, so the map uses them for violence.
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
    key: "signal",
    label: "Signals",
    description: "Non-violent events that can come before violence: protests, threats, troop movements",
    violent: false,
    color: "#6b6964",
  },
];

const BY_KEY = Object.fromEntries(CATEGORIES.map((c) => [c.key, c])) as Record<CategoryKey, Category>;

/** Violent event types by category. ACLED battles and GDELT fighting can be between armed
 *  groups too, but neither source says whether a government took part. */
export const CATEGORY_TYPES: Record<Exclude<CategoryKey, "signal">, string[]> = {
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
