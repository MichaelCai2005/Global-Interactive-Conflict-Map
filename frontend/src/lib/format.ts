const EVENT_TYPE_LABELS: Record<string, string> = {
  // UCDP
  state_based: "State-based conflict",
  non_state: "Non-state conflict",
  one_sided: "One-sided violence",
  // ACLED
  battle: "Battle",
  explosion_remote_violence: "Explosion / remote violence",
  violence_against_civilians: "Violence against civilians",
  protest: "Protest",
  riot: "Riot",
  strategic_development: "Strategic development",
  // GDELT (CAMEO roots 13-20)
  threat: "Threat",
  force_posture: "Force posture",
  reduce_relations: "Reduced relations",
  coercion: "Coercion",
  assault: "Assault",
  fight: "Fighting",
  mass_violence: "Mass violence",
};

export function eventTypeLabel(type: string): string {
  return EVENT_TYPE_LABELS[type] ?? humanize(type);
}

function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const SOURCE_LABELS: Record<string, string> = { ucdp: "UCDP", acled: "ACLED", gdelt: "GDELT" };

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source.toUpperCase();
}

export const SOURCE_DESCRIPTIONS: Record<string, string> = {
  ucdp: "Hand-coded organized violence with at least one death",
  acled: "Hand-coded political violence, protests and strategic developments",
  gdelt: "Machine-coded news events; signals before and around violence",
};

const whole = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function formatCount(n: number): string {
  return whole.format(n);
}

export function formatCompact(n: number): string {
  return n < 10_000 ? whole.format(n) : compact.format(n);
}

/** Percentage change, or null when there is no baseline to compare with. */
export function percentChange(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null;
  return ((current - previous) / previous) * 100;
}

export function formatChange(change: number | null): string {
  if (change === null) return "new";
  // Past a tenfold rise a multiple reads better than a four-digit percentage.
  if (change >= 900) return `${formatCompact(Math.round(change / 100 + 1))}×`;
  const rounded = Math.round(change);
  if (rounded === 0) return "no change";
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${formatCount(n)} ${n === 1 ? word : many}`;
}
