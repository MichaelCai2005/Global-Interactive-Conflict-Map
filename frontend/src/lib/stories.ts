import type { Bbox } from "../api/types";
import type { DateWindow } from "./dates";

/**
 * Guided starting points: a place, a stretch of time and a window length that show how a
 * well-documented conflict developed. Choosing one flies the map there and plays the
 * timeline from the start of the range.
 */
export interface Story {
  id: string;
  title: string;
  period: string;
  summary: string;
  bbox: Bbox;
  range: DateWindow;
  windowDays: number;
}

export const STORIES: Story[] = [
  {
    id: "ukraine-2022",
    title: "Russia's invasion of Ukraine",
    period: "Nov 2021 – Dec 2022",
    summary:
      "Fighting in Donbas before 24 February 2022, then several fronts at once: the push on Kyiv, the withdrawal from the north, and the battles in the east and south.",
    bbox: [22, 44, 41, 53],
    range: { start: "2021-11-01", end: "2022-12-31" },
    windowDays: 14,
  },
  {
    id: "syria",
    title: "Syria's civil war",
    period: "2011 – 2016",
    summary:
      "Protests in 2011 turn into an armed conflict that spreads across the country, with Aleppo, Homs and the Damascus suburbs among the most violent areas.",
    bbox: [35.5, 32.3, 42.5, 37.4],
    range: { start: "2011-01-01", end: "2016-12-31" },
    windowDays: 91,
  },
  {
    id: "bosnia",
    title: "The Bosnian War",
    period: "1992 – 1995",
    summary:
      "Violence from spring 1992 through the Dayton Agreement in late 1995, including the siege of Sarajevo and the Srebrenica massacre in July 1995.",
    bbox: [15.5, 42.5, 19.8, 45.4],
    range: { start: "1991-10-01", end: "1996-01-31" },
    windowDays: 60,
  },
  {
    id: "afghanistan",
    title: "Afghanistan, 2019–2021",
    period: "2019 – 2021",
    summary:
      "Years of heavy fighting, then the Taliban offensive of summer 2021 that ended with the fall of Kabul on 15 August.",
    bbox: [60.5, 29.3, 75, 38.6],
    range: { start: "2019-01-01", end: "2021-12-31" },
    windowDays: 60,
  },
  {
    id: "gaza",
    title: "Israel and Gaza",
    period: "Jul 2023 – 2025",
    summary:
      "The Hamas-led attack on Israel on 7 October 2023 and the war in Gaza that followed, alongside fighting on the Lebanese border.",
    bbox: [33.9, 29.4, 36.2, 33.5],
    range: { start: "2023-07-01", end: "2025-12-31" },
    windowDays: 30,
  },
];
