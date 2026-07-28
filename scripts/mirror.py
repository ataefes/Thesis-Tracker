#!/usr/bin/env python3
"""
Thesis Tracker — Firestore → clean query-free JSON mirror.

The live app writes everything into one Firestore document
(thesisTracker/main, ~340 KB, full of UI state). A claude.ai assistant cannot
read that reliably: its fetch tool strips query strings, so Firestore's
mask.fieldPaths cannot be used, and the whole document truncates.

This script (run by .github/workflows/mirror.yml on a schedule) reads that
document server-side, strips the UI state, and writes small, clean, query-free
files under data/ — one per table, plus a precomputed data/due.json and a
data/manifest.json index. Each has a plain raw.githubusercontent.com URL with
no query string, which the assistant CAN fetch.

Read-only mirror: the app remains the single source of truth.
"""

import json, re, sys, os, urllib.request, datetime
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Berlin")
except Exception:
    TZ = datetime.timezone.utc

MAIN_URL = ("https://firestore.googleapis.com/v1/projects/master-thesis-ata/"
            "databases/(default)/documents/thesisTracker/main")
RAW_BASE = "https://raw.githubusercontent.com/ataefes/Thesis-Tracker/main/data/"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Tables that are real data (everything else in the payload is UI state).
DATA_TABLES = [
    "plates", "schedule", "runs", "thaw", "imaging", "staining", "treatments",
    "drugs", "viruses", "reagents", "media", "coatings", "splits", "timeline",
    "questions", "reading", "experiments", "insights", "supervisor",
    "completedTasks", "skippedTasks", "log",
]
# Per-row internal keys to drop (epoch noise). _id is kept (task ids reference it).
DROP_ROW_KEYS = {"_cr", "_upd"}

# Protocol master step days + titles (mirror of the app's Protocol Reference).
# Used only to precompute due dates; defer to the app if it changes.
PROTOCOLS = {
    "npc_diff": [
        (0, "Seed embryoid bodies (EBs)"), (2, "Half-media change — FFM + Noggin"),
        (4, "Half-media change — FFM + Noggin"), (5, "Switch to NIM + Noggin"),
        (6, "NIM + Noggin"), (7, "Dissociate EBs; plate 6 EBs/well in IDM-A + Noggin"),
        (8, "Media change (IDM-A + Noggin)"), (10, "Media change (IDM-A + Noggin)"),
        (12, "Media change (IDM-A + Noggin)"),
        (14, "Dissociate; replate on PLO/laminin in NPC medium"),
    ],
    "npc_diff_9000": [
        (0, "Seed EBs (9000 cells)"), (3, "Media change — hES media"),
        (5, "Switch to NIM + Noggin"), (6, "NIM + Noggin"),
        (7, "Dissociate EBs; plate 6 EBs/well in IDM-A + Noggin"),
        (8, "Media change (IDM-A + Noggin)"), (10, "Media change (IDM-A + Noggin)"),
        (12, "Media change (IDM-A + Noggin)"),
        (14, "Dissociate; replate on PLO/laminin in NPC medium"),
    ],
}


def unwrap(v):
    """Firestore typed value -> plain Python value."""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:  return v["stringValue"]
    if "integerValue" in v: return int(v["integerValue"])
    if "doubleValue" in v:  return v["doubleValue"]
    if "booleanValue" in v: return v["booleanValue"]
    if "nullValue" in v:    return None
    if "timestampValue" in v: return v["timestampValue"]
    if "arrayValue" in v:
        return [unwrap(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: unwrap(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return v


def clean_row(row):
    if not isinstance(row, dict):
        return row
    return {k: val for k, val in row.items() if k not in DROP_ROW_KEYS}


def parse_date(s):
    """dd.mm.yy or dd.mm.yyyy (day-first) -> date, else None."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})[.](\d{1,2})[.](\d{2,4})", str(s))
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def build_due(payload, today):
    """Replicate the app's Today logic into a flat, dated list."""
    completed = set(payload.get("completedTasks", []) or [])
    skipped = set(payload.get("skippedTasks", []) or [])
    items = []

    def add(dt, title, source, notes=""):
        du = (dt - today).days
        if du > 8:                    # only overdue + this week
            return
        items.append({
            "date": dt.isoformat(), "title": title, "source": source,
            "overdue": du < 0, "days_from_today": du, "notes": notes or "",
        })

    for r in payload.get("schedule", []) or []:
        rid = "sched:" + str(r.get("_id", ""))
        if rid in completed or rid in skipped:
            continue
        dt = parse_date(r.get("date"))
        if dt:
            add(dt, r.get("task") or "(task)", "schedule", r.get("notes") or "")
        # coating/prep can be embedded in a FUTURE row's text, dated for today
        for fld in ("coating", "notes"):
            txt = str(r.get(fld) or "")
            m = re.search(r"TODAY\s*\((\d{1,2})[.](\d{1,2})", txt, re.I)
            if m:
                cd, cm = int(m.group(1)), int(m.group(2))
                if cd == today.day and cm == today.month:
                    add(today, "Coating/prep: " + txt, "schedule-embedded",
                        "From the coating field of: " + (r.get("task") or ""))

    for r in payload.get("thaw", []) or []:
        rid = "thaw:" + str(r.get("_id", ""))
        if rid in completed or rid in skipped:
            continue
        dt = parse_date(r.get("nextsplit"))
        if dt:
            add(dt, "Split due — " + (r.get("line") or ""), "thaw",
                ("-> " + r.get("pafter")) if r.get("pafter") else "")

    for run in payload.get("runs", []) or []:
        if run.get("cancelled"):
            continue
        start = parse_date(run.get("start"))
        steps = PROTOCOLS.get(run.get("protocol"))
        if not start or not steps:
            continue
        done_days = {x.strip() for x in str(run.get("done") or "").split(",") if x.strip()}
        rid0 = "proto:" + str(run.get("_id", ""))
        for day, title in steps:
            if str(day) in done_days:
                continue
            if (rid0 + ":" + str(day)) in skipped:
                continue
            dt = start + datetime.timedelta(days=day)
            add(dt, (run.get("name") or run.get("protocol")) + " — Day %d: %s" % (day, title),
                "protocol")

    items.sort(key=lambda x: (x["date"], x["source"]))
    return items


def main():
    with urllib.request.urlopen(MAIN_URL, timeout=60) as resp:
        doc = json.load(resp)
    payload_wrapped = doc.get("fields", {}).get("payload", {})
    payload = unwrap(payload_wrapped)
    update_time = doc.get("updateTime")
    now_iso = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    today = datetime.datetime.now(TZ).date()

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest_files = {}

    for tbl in DATA_TABLES:
        rows = payload.get(tbl, [])
        if isinstance(rows, list):
            rows = [clean_row(r) for r in rows]
        out = {"updated": now_iso, "source_updateTime": update_time,
               "table": tbl, "records": len(rows) if isinstance(rows, list) else 0,
               "rows": rows}
        with open(os.path.join(OUT_DIR, tbl + ".json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        manifest_files[tbl] = {"url": RAW_BASE + tbl + ".json", "records": out["records"]}

    due_items = build_due(payload, today)
    due = {"updated": now_iso, "today": today.isoformat(), "timezone": str(TZ),
           "count": len(due_items), "items": due_items,
           "note": "Overdue + next 8 days, with completed/skipped removed. "
                   "Coating/prep embedded in future rows is surfaced under source "
                   "'schedule-embedded'."}
    with open(os.path.join(OUT_DIR, "due.json"), "w", encoding="utf-8") as f:
        json.dump(due, f, ensure_ascii=False, indent=1)
    manifest_files["due"] = {"url": RAW_BASE + "due.json", "records": len(due_items)}

    manifest = {
        "project": "Thesis Tracker — Adjacent Neural Organoids (ACO / DCHS1)",
        "updated": now_iso, "source_updateTime": update_time,
        "timezone": str(TZ), "generated_by": "scripts/mirror.py (GitHub Action)",
        "note": "Read-only mirror of the live app data. Plain query-free URLs. "
                "The app (https://ataefes.github.io/Thesis-Tracker/) is the source of truth.",
        "files": manifest_files,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print("Mirror OK:", len(manifest_files), "files,", len(due_items), "due items, today", today)


if __name__ == "__main__":
    main()
