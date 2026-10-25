import { useState } from "react";

// Per-browser preferences. Storage can be unavailable (private windows); then reads come back
// empty and choices last this visit only.

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Not remembered; nothing else depends on it.
  }
}

/** A yes/no choice remembered in this browser, such as whether a section was left open. */
export function useStoredFlag(key: string, initial = false): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => {
    const stored = readStored(key);
    return stored === null ? initial : stored === "1";
  });
  const set = (next: boolean) => {
    setValue(next);
    writeStored(key, next ? "1" : "0");
  };
  return [value, set];
}
