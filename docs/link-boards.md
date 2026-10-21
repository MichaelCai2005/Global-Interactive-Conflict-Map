# Link boards

A link board starts from a news article or a topic. It suggests how the story connects to
places, armed groups, past and recent conflict events, and recorded military flights and
fires. Every link says why it exists and where the evidence comes from. An analyst accepts
or rejects each suggestion and then presents the board as a briefing on a 3D globe,
gods-eye-view, where it plays through time.

```
article or topic ─► backend (app/boards)                 ─► dashboard, Boards tab: review
                    read it: Claude, or the gazetteer        accept / reject, expand, link,
                    match places and groups to the data      notes, timeline scrubbing
                    suggest links by rule, with reasons
                    record live feeds (app/live)          ─► gods-eye-view fork: present
                    export a Director scene                  one shot per time step,
                                                             live military flights now
```

## Running it

Four processes, each in its own terminal:

```bash
# 1. API (backend/)
uvicorn app.main:app --port 8000

# 2. Dashboard (frontend/), Boards tab
npm run dev                                   # http://localhost:5173

# 3. Military-flight recorder (backend/), keeps a history of the live feed
python -m app.live adsb                       # polls adsb.lol every 2 minutes

# 4. The globe: the gods-eye-view fork, next to this repo (Node 24.14 or newer)
CONFLICT_MAP_API=http://localhost:8000 npm run dev    # http://localhost:4173
```

On the Boards tab, paste an article link, or the article's text for paywalled sites, or
name a topic. After review, **Open in 3D globe** opens the board in the globe at
`?board=<id>`. **Download for globe** saves a `.gevbundle.json`. The unmodified upstream
globe can import that file from Scenes > IMPORT, with no API and no fork.

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

## Presenting on the globe

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
