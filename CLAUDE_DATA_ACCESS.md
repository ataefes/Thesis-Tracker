# Thesis Tracker — live data access for Claude

**guide_version: 2026-07-29.1** — cross-check against `manifest.json`'s `guide_version`. If
they differ, you are reading a **cached old copy of this guide** (re-fetch, or start a fresh
conversation) — trust `manifest.json`'s value as the current one.

This tells an assistant (e.g. Claude in a claude.ai Project) how to read the current data
of the Thesis Tracker on demand — "what do I need to do today?", "which plates are fixed?",
"what day is my NPC run on?". Fetch fresh each time.

The app (https://ataefes.github.io/Thesis-Tracker/) is the single source of truth (it
writes the live Firestore doc). A GitHub Action mirrors that into the small, clean,
**query-free** JSON files described below (refreshed ~every 15 min). **Read-only** — to
change anything, the user edits the app.

---

## 1. How to fetch — use these plain URLs (NO query strings)

> ⚠️ Do **not** put a `?query=...` on these URLs — some fetch tools strip query strings, and
> do **not** fetch the raw Firestore document (`thesisTracker/main`) — it is ~340 KB and
> **truncates**, dropping tables silently. Use the per-file URLs below; each is small.

**Index (read first):**
```
https://raw.githubusercontent.com/ataefes/Thesis-Tracker/main/data/manifest.json
```
It lists every file's absolute URL, record count, and `updated` (freshness).

**"What's due" — the most common question.** Precomputed today/this-week list, with
completed/skipped already removed and dates already worked out (no date math needed):
```
https://raw.githubusercontent.com/ataefes/Thesis-Tracker/main/data/due.json
```

**Any single table** — swap `plates` for a table name from §3:
```
https://raw.githubusercontent.com/ataefes/Thesis-Tracker/main/data/plates.json
```

Fetch only the file(s) a question needs. `due.json` answers "today / this week / what
should I do". For everything else, fetch the specific table.

---

## 2. File shape

Every file is plain JSON (already unwrapped — no Firestore typed-value envelope):
```json
{ "updated": "2026-07-28T21:07:...+02:00", "table": "plates", "records": 23, "rows": [ { … }, … ] }
```
`rows` is the array of records. Each row keeps its internal `_id` (task ids reference it,
§5); the epoch-noise fields `_cr`/`_upd` are stripped. `updated` is when the mirror last
ran (freshness). `due.json` and `manifest.json` have their own top-level shape.

---

## 3. Tables (one file each: `data/<table>.json`)

| File | What it is | Main columns |
|---|---|---|
| `due` | **Precomputed** today + next 8 days (see §5) | rows: `date`, `title`, `source`, `overdue`, `days_from_today`, `notes` |
| `plates` | Every plate | `plate` (name/id), `start` (seeding date), `lines`, `dens`, `status` (lowercased: active/fixed/died), `treatment`, `imaging`, `dup`, `fixDate`, `note` |
| `schedule` | Dated tasks & reminders | `date`, `task`, `coating`, `notes` |
| `runs` | Protocol runs in progress | `name`, `protocol`, `start` (**Day 0 date**), `done` (comma-list of done day numbers), `cancelled`, `notes` |
| `thaw` | iPSC thaw / culture | `date`, `line`, `pthaw`, `medium`, `coating`, `nextsplit` (**next split due**), `pafter`, `notes` |
| `imaging` | Imaging sessions | `date`, `plate`, `line`, `modality` (Calcium/Live/Confocal/MICA), `dye`, `stain`, `result`, `analysis`, `wells`, `note` |
| `staining` | Antibody / IHC records | `marker`, `primary`, `host`, `lot`, `pdil` (primary dilution), `secondary`, `sdil`, `fix`, `perm`, `usedon`, `result`, `note` |
| `treatments` | Drug / virus log | `plate`, `date`, `line`, `type` (Drug/Virus), `substance`, `conc`, `wells`, `by`, `note` |
| `drugs` | Drug reference | `drug`, `have`, `cat`, `form`, `stock`, `test`, `stab`, `store`, `note` |
| `viruses` | Virus reference | `name`, `serotype`, `promoter`, `payload`, `titer`, `source`, `have`, `store`, `note` |
| `reagents` | Reagent stock | `name`, `cat`, `company`, `conc`, `storage`, `stock` (yes/low/no/ordered), `note` |
| `media` | Media recipes | `name`, `comp`, `add`, `storage`, `notes` |
| `coatings` / `splits` | Coating & split events | `date`, `line`, `label`, `note`, matrix/map fields |
| `timeline` | High-level plan | `period`, `goal`, `status` (planned/in progress/done), `note`, `checked` |
| `questions` | Open questions | `date`, `topic`, `q`, `ask`, `status`, `answer` |
| `reading` | Reading list | `source`, `topic`, `prio`, `read`, `takeaway`, `section` |
| `experiments` | Experiment log | `date`, `type`, `line`, `did`, `result`, `problem`, `batch`, `file` |
| `insights` | Methodology insights | `date`, `topic`, `insight`, `evidence`, `status`, `section` |
| `supervisor` | "From Rebecca" inbox | `text`, `by`, `at`, `done` |
| `completedTasks` | ids of tasks marked **done** (§5) | rows are id strings |
| `skippedTasks` | ids of tasks marked **not done** | rows are id strings |
| `log` | recent done/skip actions | `id`, `title`, `tag`, `action`, `at` |

(UI-state — `colWidths`, `rowMeta`, `plateMaps`, `plateEffects`, `customCols`, `_rev*`
flags — is intentionally not mirrored.)

---

## 4. Conventions (this project has had date/plate mix-ups — read this)

- **Dates are day-first strings**, `dd.mm.yy` **or** `dd.mm.yyyy` — **both occur in the same
  table** (`29.04.26` and `10.07.2026`). Read as day.month.year; `10.07.2026` = 10 July 2026,
  never month-first. Some plate `start`s are approximate (`>19.06.26`).
  (`due.json` dates are already normalised to ISO `YYYY-MM-DD`.)
- **Plate identity** = the `plate` field (`Plate 1`, `Rebecca confocal`). Date-style names
  like "2.6 plate" appear only in free text; match on seeding date if unsure.
- `—` / empty = "not set". `[confirm]` / `[TBD]` = the user still needs to fill it in.

---

## 5. `due.json` — what it already did for you

`due.json` is the app's "Today" logic, precomputed, so you don't do date arithmetic:
- Combines `schedule` dates, `thaw` `nextsplit` dates, and non-cancelled `runs`' protocol
  step dates (`start` + step-day).
- Removes anything already in `completedTasks` / `skippedTasks` (or a run's done days).
- Covers **overdue + the next 8 days**; `overdue: true` flags past-due items.
- **Surfaces the coating/prep trap:** a coating action can be written inside a *future*
  row's `coating` text (e.g. tomorrow's thaw row says "Coat plates TODAY (28.07)…"). Those
  appear as items with `source: "schedule-embedded"`, dated today — so "nothing today" is
  never wrong by omission.

Each `due` row: `date` (ISO), `title`, `source` (`schedule` / `thaw` / `protocol` /
`schedule-embedded`), `overdue` (bool), `days_from_today` (int), `notes`.

### ⚠️ Staleness self-check — do this every time before trusting due.json

This is a **mirror**, not live. A GitHub Action refreshes it, but GitHub heavily throttles
scheduled jobs on public repos — in practice it runs **every few hours, not every 15 min**,
and can lag longer. On top of that, `raw.githubusercontent.com` caches ~5 min and your own
fetch tool may cache a URL for ~15 min. So a just-made app edit can take a while to appear,
and if you fetched earlier in a long conversation you may be holding an old copy.

1. Read the `today` field in `due.json` and compare it to the **real current date**.
   - If `today` **≠** real today, the mirror has not run yet today. The list is from
     `today`. **Tell the user how old the data is** and that a very recent edit may not
     show, and suggest confirming in the app. Do **not** present it as "today".
2. `overdue` and `days_from_today` are **frozen at mirror time**. Only trust them if
   `due.json` `today` **==** the real today. Otherwise **recompute** each item's status
   yourself from its `date` vs the real today (e.g. an item dated for `today`'s value may no
   longer be "in 1 day"; a `days_from_today: 1` from yesterday is due **today** now).

For raw fields behind an item, open the matching table file. Task-id scheme (if you ever
need it): schedule → `sched:<_id>`, thaw → `thaw:<_id>`, run step → `proto:<run _id>:<day>`.

---

## 6. Worked examples

- **"What do I need to do today / this week?"** → `due.json` only.
- **"Which plates are fixed?"** → `plates.json`; rows with `status` = `fixed`. (All `status`
  values are lowercased in the mirror — `fixed`/`died`/`active` — so match lowercase.)
- **"What did Rebecca ask me?"** → `supervisor.json`; rows with `done` = false.
- **"Antibody dilution for Pax6?"** → `staining.json`; row `marker`=`Pax6` → `pdil`.
- **"How many days into the F1 run am I?"** → `runs.json`; row `name`="F1": today − `start`.

---

## 7. Freshness & limits

Three timestamps, three different meanings — don't confuse them:
- **`manifest.updated`** = when the **mirror last ran** (advances every run, ~every few
  hours). A recent value here means the pipeline is alive; it does **not** mean the data
  changed.
- **`source_updateTime`** (in `manifest.json` and each file) = when the **app data last
  changed**. If this is old, the user simply hasn't edited anything since — that's normal,
  not a failure.
- **`due.json.today`** = the date the "what's due" list was computed for → the staleness
  self-check in §5. If it ≠ the real today, warn and recompute.

Caching: GitHub throttles the scheduled refresh to **every few hours** (not 15 min), and
raw/​your-fetch caches add minutes on top. So:
- An edit made seconds/minutes ago may not be reflected yet — say so and offer to re-check.
- If you suspect you're holding a cached copy (e.g. `guide_version` here ≠ `manifest`'s, or
  `due.json.today` is old), the **cache-free** path is the GitHub contents API, which returns
  the current file (base64 in `.content`, decode it), e.g.
  `https://api.github.com/repos/ataefes/Thesis-Tracker/contents/data/plates.json` — or just
  start a fresh conversation so nothing is cached.
- Read-only. To change data, the user edits the app; it flows back here on the next refresh.
