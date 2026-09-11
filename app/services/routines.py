"""Haushalt — wiederkehrende Routinen.

Zwei Entscheidungen stecken hier drin, beide bewusst:

1. Der Rhythmus zählt ab der letzten Erledigung, nicht ab einem festen
   Kalendertag. Wer eine Woche nicht da war, kommt sonst zu einem Berg
   heim, der sich täglich weiter auftürmt.
2. Wer eine Routine dreimal hintereinander wegdrückt, meint nicht sich
   selbst, sondern den Rhythmus. Kompass streckt ihn dann von allein und
   sagt es — statt weiter jeden Tag dasselbe zu fordern.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..db import get_db, log_event, parse_day, rows_to_dicts, today_str

SKIPS_BEFORE_STRETCH = 3
FIELDS = ("title", "room", "interval_days", "duration_min", "energy", "note",
          "active", "sort_order", "next_due")


def create(data: dict[str, Any]) -> dict[str, Any]:
    row = {
        "title": (data.get("title") or "").strip(),
        "room": data.get("room") or None,
        "interval_days": float(data.get("interval_days") or 7),
        "duration_min": int(data.get("duration_min") or 10),
        "energy": data.get("energy") or "mittel",
        "note": data.get("note"),
        "next_due": data.get("next_due") or today_str(),
        "sort_order": int(data.get("sort_order") or 100),
    }
    if not row["title"]:
        raise ValueError("Eine Routine braucht einen Titel.")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO routines(title, room, interval_days, duration_min,
                                    energy, note, next_due, sort_order)
               VALUES(:title,:room,:interval_days,:duration_min,:energy,:note,
                      :next_due,:sort_order)""", row)
        new_id = cur.lastrowid
    return get(new_id)


def get(routine_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM routines WHERE id=?", (routine_id,)).fetchone()
    if not row:
        raise KeyError(f"Routine {routine_id} gibt es nicht.")
    return _decorate(dict(row))


def update(routine_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in FIELDS:
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if sets:
        values.append(routine_id)
        with get_db() as db:
            db.execute(f"UPDATE routines SET {', '.join(sets)} WHERE id=?", values)
    return get(routine_id)


def delete(routine_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM routines WHERE id=?", (routine_id,))


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    due = parse_day(row.get("next_due"))
    today = date.today()
    row["overdue_days"] = (today - due).days if due else 0
    row["due_today"] = bool(due and due <= today)
    last = parse_day(row.get("last_done"))
    row["days_since"] = (today - last).days if last else None
    return row


def query(active_only: bool = True, room: str | None = None) -> list[dict[str, Any]]:
    where = ["1=1"]
    args: list[Any] = []
    if active_only:
        where.append("active=1")
    if room:
        where.append("room=?")
        args.append(room)
    with get_db() as db:
        rows = db.execute(
            f"""SELECT * FROM routines WHERE {' AND '.join(where)}
                ORDER BY (next_due IS NULL), next_due, sort_order, id""",
            args).fetchall()
    return [_decorate(dict(r)) for r in rows]


def due(day: str | None = None) -> list[dict[str, Any]]:
    """Was heute (oder früher) fällig ist — das Herz des Haushaltsteils."""
    day = day or today_str()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM routines WHERE active=1 AND (next_due IS NULL OR next_due<=?) "
            "ORDER BY next_due, sort_order", (day,)).fetchall()
    return [_decorate(dict(r)) for r in rows]


def complete(routine_id: int, note: str | None = None) -> dict[str, Any]:
    """Erledigt: Rhythmus läuft ab jetzt neu."""
    routine = get(routine_id)
    interval = float(routine["interval_days"] or 7)
    next_due = (date.today() + timedelta(days=interval)).isoformat()
    with get_db() as db:
        db.execute(
            "UPDATE routines SET last_done=?, next_due=?, streak=streak+1, skips=0 "
            "WHERE id=?", (today_str(), next_due, routine_id))
        db.execute("INSERT INTO routine_log(routine_id, day, note) VALUES(?,?,?)",
                   (routine_id, today_str(), note))
    return get(routine_id)


def snooze(routine_id: int, days: int = 1) -> dict[str, Any]:
    """Weggedrückt. Beim dritten Mal streckt Kompass den Rhythmus selbst."""
    routine = get(routine_id)
    base = parse_day(routine.get("next_due")) or date.today()
    new_due = max(base, date.today()) + timedelta(days=days)
    skips = int(routine.get("skips") or 0) + 1
    stretched = None
    interval = float(routine["interval_days"] or 7)
    if skips >= SKIPS_BEFORE_STRETCH:
        stretched = round(interval * 1.5, 1)
        skips = 0
    with get_db() as db:
        if stretched:
            db.execute("UPDATE routines SET next_due=?, skips=0, interval_days=? "
                       "WHERE id=?", (new_due.isoformat(), stretched, routine_id))
        else:
            db.execute("UPDATE routines SET next_due=?, skips=? WHERE id=?",
                       (new_due.isoformat(), skips, routine_id))
    if stretched:
        log_event("haushalt",
                  f"„{routine['title']}“ hast du dreimal weggeschoben — "
                  f"Rhythmus von {interval:g} auf {stretched:g} Tage gestreckt.")
    return get(routine_id)


def split_hint(routine: dict[str, Any]) -> str | None:
    """Große Brocken lassen sich schlecht anfangen. Kleiner schneiden hilft."""
    if int(routine.get("duration_min") or 0) >= 20 and int(routine.get("skips") or 0) >= 2:
        return (f"„{routine['title']}“ dauert {routine['duration_min']} Minuten und "
                f"bleibt liegen. Mach nur den ersten Teil — das zählt auch.")
    return None


def stats() -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM routines WHERE active=1) AS gesamt,
                 (SELECT COUNT(*) FROM routines WHERE active=1
                    AND next_due<=date('now','localtime')) AS fällig,
                 (SELECT COUNT(*) FROM routines WHERE active=1
                    AND next_due<date('now','localtime','-3 day')) AS lange_ueberfaellig,
                 (SELECT COUNT(*) FROM routine_log
                    WHERE day>=date('now','localtime','-7 day')) AS woche_erledigt
            """).fetchone()
    return dict(row)


def history(routine_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM routine_log WHERE routine_id=? ORDER BY id DESC LIMIT ?",
            (routine_id, limit)).fetchall()
    return rows_to_dicts(rows)


def rooms() -> list[str]:
    with get_db() as db:
        rows = db.execute(
            "SELECT DISTINCT room FROM routines WHERE room IS NOT NULL "
            "ORDER BY room").fetchall()
    return [r["room"] for r in rows]
