# Link boards

A link board starts from a news article or a topic. It suggests how the story connects to
places, armed groups, past and recent conflict events, and recorded military flights and
fires. Every link says why it exists and where the evidence comes from. The board opens as
a canvas you arrange like a mood board: keep or dismiss suggestions, add notes, pictures,
links and more articles, and draw your own connections.

```
article or topic ─► backend (app/boards)                 ─► dashboard, Boards tab: the
                    read it: Claude, or the gazetteer        canvas (cards and lines), the
                    match places and groups to the data      map, or both side by side;
                    suggest links by rule, with reasons      the sidebar shows the selected
                    record live feeds (app/live)             card with its source, picture
                                                             and connections
```

Presenting a board on the gods-eye-view 3D globe is paused for now; its export still works
(see "Presenting on the globe" below).

## Running it

Up to three processes, each in its own terminal:

```bash
# 1. API (backend/)
uvicorn app.main:app --port 8000

# 2. Dashboard (frontend/), Boards tab
npm run dev                                   # http://localhost:5173

# 3. Optional: military-flight recorder (backend/), keeps a history of the live feed
python -m app.live adsb                       # polls adsb.lol every 2 minutes
```

On the Boards tab, paste an article link (or the article's text, for paywalled sites),
name a topic, or start a blank board.

Optional:

- `ANTHROPIC_API_KEY` in `backend/.env` plus `pip install -e ".[ai]"`: Claude reads the
  article (`claude-opus-5-5`). It finds claims ("an airstrike hit X on Tuesday"), places
  the events data has never seen, and groups under any name. Without it, a gazetteer
  extractor uses only the names already in the events data.
- `FIRMS_MAP_KEY`: `python -m app.live firms --bbox 22,44,41,53 --start 2026-10-01 --days 10`
  records NASA fire detections, including past days.
- `python -m app.ingest download gdelt --start … --end …` and `load gdelt …` keep recent
  events current. UCDP's last release ends in 2025, and the ACLED download here covers
  2022.

## Working on the board

The main area shows the open board as a canvas. **Board**, **Board + map** and **Map**
switch between the canvas, both side by side, and the map alone.

- **Cards.** Each place, group, event, article, note, link or picture is a card. Its colour
  is its kind. Dashed cards are suggestions, with **Keep** and **Dismiss** on them. A card
  with a source has a link that opens it in a new tab, and ◉ means it is on the map.
- **Click** a card or line to open it in the sidebar. There you can edit its title and
  notes, open its source, add or change its picture, pin it to the map, jump to anything
  it is connected to, or **Find more around this** (expand).
- **Drag** cards to arrange them; the spot is saved. The first move also saves every
  other card where it is, so later layouts don't shift them. **Tidy up** lays the whole
  board out again.
- **Connect** two cards by dragging the blue dot on a card's edge onto another card, then
  say what connects them. That label shows on the line. **Connect to…** in the sidebar
  does the same from a list.
- **Add** with the toolbar: a note, a picture (upload PNG, JPEG, GIF or WebP up to 5 MB,
  or paste its link), a link to any page, or another article. An added article is read
  and linked like the first one, so its places and events join the cards already there.
  **Double-click** the canvas for a quick note, and **drop** pictures or links onto it.
- **Find a card** searches titles; Enter jumps to the first match. Turn **Suggestions** off
  to see only what you kept and added.

Until someone moves them, cards are laid out as a mind map from left to right: the
articles and your own cards first, then what they name, then the events around those. A
card with many children gets them as a block of a few columns (`frontend/src/board/layout.ts`).

Uploaded pictures are stored in the database (`board_images`) and served at
`/boards/images/<id>`, readable by whoever can read their board. SVG is refused, since
it can carry script. Notes and links need no place on the map; **Pin to map centre** gives
them one.

## How a board is built

1. **Read.** Fetch the article (public addresses only, 3 MB cap) and take its title, date
   and paragraphs. A topic is searched with GDELT's article search (last 3 months,
   English). If that search is down or finds nothing, the board is built from the topic's
   own words.
2. **Extract.** List the places, groups, claims and focus countries. Focus countries are
   the ones named at least 40% as often as the most named one. A dateline or a summit
   venue stays on the board, but it doesn't pull in events.
3. **Resolve.** Places are matched against the half-million located events, by the names
   the sources use. Same-name places are told apart by country and by distance to the
   story's other places, and the card says when there was a choice. Groups are matched to
   UCDP and ACLED actor names through aliases ("Russian troops" means "Military Forces of
   Russia" and UCDP's "Government of Russia"). GDELT matches through its CAMEO codes
   (`RUSMIL`).
4. **Link.** The rules below run, each capped so the board stays readable (at most 60
   events).

| Rule | From → to | Reason it gives |
| --- | --- | --- |
| `mentions` | article → place, group | the article names it, with the sentence |
| `reports` | article → claim | the article says this happened (Claude only) |
| `coded_from` | article → event | GDELT coded this event from this very article |
| `near` | place, claim, event → event, flight, fire | km apart and days apart |
| `history` | place → event | the deadliest UCDP/ACLED events there in the 3 years before |
| `same_actor` | group → event | the source names the group, or GDELT codes it |
| `same_incident` | event → event | ingest matched two sources' reports of one incident |
| `co_reported` | event → event | GDELT coded both from one news report |
| `user` | anything | an analyst drew it |

Confidence runs from 0 to 1. It says how closely the item ties to the story, as a plain
formula of distance, time and match quality (`app/boards/rules.py`). It is not a trained
probability, and nothing is shown on the globe until it is accepted, unless you choose
"Everything not rejected".

**Expand** on any item asks for more connections around it:
- **Events:** nearby events, the event's actors, and other sources' reports of the same
  incident.
- **Groups:** their three-year record in the story's region.
- **Anything with a place:** recorded flights and fires.

## Presenting on the globe (paused)

The dashboard no longer links to the globe, but the API still exports to it:
`/boards/<id>/bundle` and `/boards/<id>/scene.json`. Notes, links and pictures with no
place on the map are left out of the export.

The export is a gods-eye-view Director scene, version 6. The steps are:

1. "The story": the article, places and groups.
2. "How we got here": history.
3. Up to five steps through the recent days.
4. For stories from the last 14 days, a final "Now" shot that turns on the globe's live
   military flights, GPS interference and fires.

Each step is a data pack, and each shot shows the packs up to that point, so the board
grows as the briefing plays. Clicking a point or a line opens a card with what it is, why
it is there, the quote and the source link.

The export keeps to the globe's limits: 8 packs, 2,000 features a pack, 64 cards a shot,
and card links without query strings (tracking parameters are dropped; other links are
written into the card text). Points are lifted 80 m above ground heights from Open-Meteo.
Links are raised great-circle arcs, and items at the same spot fan out in a small ring.

`tools/check_gev_scene.mjs` runs an export through the globe's own validators.
`tools/qa_globe_board.mjs` plays a board in a running globe and takes a screenshot of
each shot (see the files for usage).

## The gods-eye-view fork

The fork is a branch, `conflict-map-integration`, of
[gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) (MIT), cloned next to this
repo. Its changes are listed in that repo's `docs/CONFLICT-MAP.md`. In short:
- **Colours and labels:** board points are coloured by kind and labelled, and suggested
  links are dashed.
- **API source:** a `conflict-map` pack source reads boards from this API through the
  globe's own server.
- **Links:** `?board=<id>` opens a board, keeping the person's own scenes.

## Limits to keep in mind

- **Coverage.** UCDP ends in 2025 and the ACLED download covers 2022, so recent context
  comes from GDELT. GDELT is machine-coded from news, unverified, and places events at
  city centres. Cards say so.
- **Name meanings change.** UCDP's "Government of Yemen (North Yemen)" is the Houthi-run
  government in recent data, so it is shown as "Houthis (UCDP: Government of Yemen)"
  (`SPECIAL_ACTORS` in `app/boards/names.py`). Check the actor names before briefing a
  conflict you don't know.
- **Live feeds only have history from when recording began.** The military-flight feed
  covers what volunteer receivers hear, mostly Europe and North America.
- **People.** Private individuals are not extracted or linked: groups, places, events and
  military assets only.
- **Licences.** ACLED's terms do not allow redistributing its data, so share bundles
  containing ACLED events only within the terms of your access. UCDP is CC BY 4.0. The
  free Cesium ion plan is for non-commercial use.
