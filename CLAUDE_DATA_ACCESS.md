# Thesis Tracker — live data access for Claude

This document tells an assistant (e.g. Claude in a claude.ai Project) how to read the
**current, live** data of the Thesis Tracker on demand — e.g. "what do I need to do
today?", "which plates are fixed?", "what day is my NPC run on?". Fetch fresh each time.

The tracker UI (https://ataefes.github.io/Thesis-Tracker/) reads and writes this same
data, so it is the single source of truth. **This is read-only** — to change anything,
the user edits it in the app.

---

## 1. How to fetch — ALWAYS use targeted (masked) fetches

⚠️ **Do NOT fetch the whole document.** It is ~340 KB (lots of UI state) and will
**truncate**, so tables near the end silently go missing. Instead fetch only the
table(s) you need, using Firestore's `mask.fieldPaths` (nested paths work). Each masked
fetch is small (0.3–35 KB).

**Base document:**
```
https://firestore.googleapis.com/v1/projects/master-thesis-ata/databases/(default)/documents/thesisTracker/main
```

**Per-table pattern** — append one query param per table you want:
```
<base>?mask.fieldPaths=payload.<TABLE>
<base>?mask.fieldPaths=payload.plates&mask.fieldPaths=payload.runs      (multiple at once)
```
Add `&mask.fieldPaths=updateTime` to also get the document's last-write timestamp
(freshness). Response shape is unchanged — the returned tables sit at
`fields.payload.mapValue.fields.<TABLE>` (see §2).

### Ready-made URLs

**"What's due" / planning bundle** (schedule + thaw + runs + coatings + splits + the
done/skip sets + supervisor) — ~46 KB, use this for any "today / this week / what should
I do" question:
```
https://firestore.googleapis.com/v1/projects/master-thesis-ata/databases/(default)/documents/thesisTracker/main?mask.fieldPaths=payload.schedule&mask.fieldPaths=payload.thaw&mask.fieldPaths=payload.runs&mask.fieldPaths=payload.coatings&mask.fieldPaths=payload.splits&mask.fieldPaths=payload.completedTasks&mask.fieldPaths=payload.skippedTasks&mask.fieldPaths=payload.supervisor
```

**Single table** — swap `plates` for any table name from §3:
```
https://firestore.googleapis.com/v1/projects/master-thesis-ata/databases/(default)/documents/thesisTracker/main?mask.fieldPaths=payload.plates
```

**Everything, data-only** (all 22 real tables, UI state excluded) — ~185 KB, only when a
question spans many tables; may still be large, so prefer per-table when you can:
```
https://firestore.googleapis.com/v1/projects/master-thesis-ata/databases/(default)/documents/thesisTracker/main?mask.fieldPaths=payload.plates&mask.fieldPaths=payload.schedule&mask.fieldPaths=payload.runs&mask.fieldPaths=payload.thaw&mask.fieldPaths=payload.imaging&mask.fieldPaths=payload.staining&mask.fieldPaths=payload.treatments&mask.fieldPaths=payload.drugs&mask.fieldPaths=payload.viruses&mask.fieldPaths=payload.reagents&mask.fieldPaths=payload.media&mask.fieldPaths=payload.coatings&mask.fieldPaths=payload.splits&mask.fieldPaths=payload.timeline&mask.fieldPaths=payload.questions&mask.fieldPaths=payload.reading&mask.fieldPaths=payload.experiments&mask.fieldPaths=payload.insights&mask.fieldPaths=payload.supervisor&mask.fieldPaths=payload.completedTasks&mask.fieldPaths=payload.skippedTasks&mask.fieldPaths=payload.log
```

**If a response still looks truncated** (JSON doesn't close, a table you expected is
absent): re-fetch that specific table on its own with the per-table URL. Never answer
from a half-parsed payload without saying so.

---

## 2. Response shape (Firestore REST — typed values)

Firestore wraps every value in a one-key type object. Unwrap as you read:

| Wrapper | Meaning |
|---|---|
| `{"stringValue": "x"}` | the string `"x"` |
| `{"integerValue": "5"}` | the number `5` |
| `{"booleanValue": true}` | boolean |
| `{"nullValue": null}` | null |
| `{"arrayValue": {"values": [ … ]}}` | a list |
| `{"mapValue": {"fields": { … }}}` | an object |

Data path (after masking, only the requested tables are present):
```
fields.payload.mapValue.fields.<TABLE>.arrayValue.values[] .mapValue.fields.<COLUMN>.<typeValue>
```
Example — first plate's status:
`fields.payload.mapValue.fields.plates.arrayValue.values[0].mapValue.fields.status.stringValue`

Each row also has an internal `_id` (and sometimes `_cr`/`_upd` = created/updated epoch
ms). Ignore keys starting with `_` unless you need them. `updateTime` (top level, if you
masked it in) is the document's last-write time.

---

## 3. Tables (each is an array of row objects)

| Table (key) | What it is | Main columns |
|---|---|---|
| `plates` | Every plate | `plate` (name/id), `start` (seeding date), `lines`, `dens` (cell density), `status` (active/FIXED/DIED), `treatment` (Drug/Virus/…), `imaging`, `dup` (replicate of), `fixDate`, `note` |
| `schedule` | Dated tasks & reminders (drives "Today") | `date`, `task`, `coating`, `notes` |
| `runs` | Protocol runs in progress | `name`, `protocol` (key), `start` (**Day 0 date**), `done` (comma-list of completed day numbers), `cancelled` (bool), `notes`, `stepEdits` |
| `thaw` | iPSC thaw / culture | `date`, `line`, `pthaw` (passage), `medium`, `coating`, `nextsplit` (**next split due date**), `pafter`, `notes` |
| `imaging` | Imaging sessions | `date`, `plate`, `line`, `modality` (Calcium/Live/Confocal/MICA), `dye`, `stain`, `result`, `analysis`, `wells`, `note` |
| `staining` | Antibody / IHC records | `marker`, `primary`, `host`, `lot`, `pdil` (primary dilution), `secondary`, `sdil`, `fix`, `perm`, `usedon`, `result`, `note` |
| `treatments` | Drug / virus log | `plate`, `date`, `line`, `type` (Drug/Virus), `substance`, `conc`, `wells`, `by`, `note` |
| `drugs` | Drug reference | `drug`, `have`, `cat`, `form`, `stock`, `test`, `stab`, `store`, `note` |
| `viruses` | Virus reference | `name`, `serotype`, `promoter`, `payload`, `titer`, `source`, `have`, `store`, `note` |
| `reagents` | Reagent stock | `name`, `cat` (category), `company`, `conc`, `storage`, `stock` (yes/low/no/ordered), `note` |
| `media` | Media recipes | `name`, `comp`, `add`, `storage`, `notes` |
| `coatings` / `splits` | Coating & split events | `date`, `line`, `label`, `note`, matrix/map fields |
| `timeline` | High-level plan | `period`, `goal`, `status` (planned/in progress/done), `note`, `checked` |
| `questions` | Open questions | `date`, `topic`, `q`, `ask`, `status` (open/researching/solved), `answer` |
| `reading` | Reading list | `source`, `topic`, `prio`, `read`, `takeaway`, `section` |
| `experiments` | Experiment log | `date`, `type`, `line`, `did`, `result`, `problem`, `batch`, `file` |
| `insights` | Methodology insights | `date`, `topic`, `insight`, `evidence`, `status`, `section` |
| `supervisor` | "From Rebecca" inbox | `text`, `by`, `at`, `done` |
| `completedTasks` | ids of tasks marked **done** (§5) | array of strings |
| `skippedTasks` | ids of tasks marked **not done / skipped** | array of strings |
| `log` | recent done/skip actions | `id`, `title`, `tag`, `action` (done/skipped), `at` (epoch ms) |

(UI-state keys `colWidths`, `rowMeta`, `plateMaps`, `plateEffects`, `customCols`, and any
`_rev*` / `_*` migration flags are **not data** — never fetch or reason about them.)

---

## 4. Conventions (this project has had date/plate mix-ups — read this)

- **Dates are strings, day-first**, in `dd.mm.yy` **or** `dd.mm.yyyy` — **both formats occur
  in the same table** (e.g. `29.04.26` and `10.07.2026`). Always read as day.month.year;
  `10.07.2026` = 10 July 2026, never July-10-month-first. Some are approximate (`>19.06.26`).
- **Plate identity** = the `plate` field (a name like `Plate 1`, or `Rebecca confocal`).
  Older date-style names (e.g. "2.6 plate" = seeded 02.06) appear only in free text; match
  on seeding date when unsure.
- `—` or empty = "not set". `[confirm]` / `[TBD]` = the user still needs to fill it in.

---

## 5. Deriving "what's due" (how the app builds Today) — and a trap

A task is **still to do** if its id is in NEITHER `completedTasks` NOR `skippedTasks`.
Ids: schedule row → `sched:<_id>`; thaw split → `thaw:<_id>`; run step → `proto:<run _id>:<day>`.

To answer **"what do I need to do today / this week?"**:
1. `schedule` rows whose `date` is today-or-earlier (overdue) up to ~a week out, minus ids
   already in `completedTasks`/`skippedTasks`.
2. `thaw` rows whose `nextsplit` is in that window (id `thaw:<_id>`).
3. `runs` that are not `cancelled`: each protocol step's real date = `start` (Day 0) + step
   day number; drop days already in that run's `done` and ids in `skippedTasks`.
4. `supervisor` rows where `done` is false (things Rebecca asked for).

⚠️ **Prep/coating trap:** a "today" action can be **embedded in a future-dated row's text**,
not in a row dated today. Example: today has no `schedule` row, but tomorrow's "Thaw NPC
lines" row carries `coating: "Coat plates TODAY (28.07) — one day before thawing"`. So when
building "today", also scan the `coating` and `notes` fields of the next few upcoming rows
for a today reference (coating is usually done the day **before** a split/plating/thaw).
Don't answer "nothing today" from date-matching alone.

`runs[].done` = comma-separated completed **day numbers** (`"0,2"` = Day 0 & 2 done).
`runs[].start` = Day-0 calendar date, so Day N = `start + N days`. Exact step lists live in
the app's **Protocol Reference** page (not in this payload). The main NPC differentiation
protocol currently has steps on days 0, 2, 4, 5, 6, 7, 8, 10, 12, 14 — but defer to the
app's Protocol Reference if the user changed it.

---

## 6. Worked examples

- **"Which plates are fixed?"** → fetch `payload.plates`; rows with `status` = `FIXED`;
  report `plate`, `fixDate`, `note`.
- **"What did Rebecca ask me?"** → fetch `payload.supervisor`; rows with `done` = false.
- **"Antibody dilution for Pax6?"** → fetch `payload.staining`; row `marker`=`Pax6` → `pdil`.
- **"How many days into the F1 run am I?"** → fetch `payload.runs`; row `name`="F1":
  today − `start` = current day number; `done` shows ticked days.

---

## 7. Freshness & limits

- Data is live (read at query time). This guide on `raw.githubusercontent.com` is cached
  ~5 min; the Firestore URLs return current state.
- Read-only. To edit, the user uses the app (https://ataefes.github.io/Thesis-Tracker/);
  changes appear here immediately.
