"""Menschen — bewusst schlank gehalten.

Kein Adressbuch, keine Beziehungsverwaltung. Nur die drei Dinge, die im
Alltag wirklich untergehen: wann du dich zuletzt gemeldet hast, wann ein
Geburtstag ansteht, und was du dir über jemanden gemerkt hast.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..db import get_db, now_str, parse_day, rows_to_dicts, today_str

FIELDS = ("name", "birthday", "cadence_days", "note", "tags", "active", "last_contact")


def create(data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Ohne Namen geht es nicht.")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO people(name, birthday, cadence_days, note, tags, last_contact)
               VALUES(?,?,?,?,?,?)""",
            (name, data.get("birthday") or None,
             int(data["cadence_days"]) if data.get("cadence_days") else None,
             data.get("note"), data.get("tags"), data.get("last_contact")))
        person_id = cur.lastrowid
    return get(person_id)


def get(person_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not row:
        raise KeyError(f"Person {person_id} gibt es nicht.")
    return _decorate(dict(row))


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    last = parse_day(row.get("last_contact"))
    row["days_since"] = (today - last).days if last else None
    cadence = row.get("cadence_days")
    if cadence and row["days_since"] is not None:
        row["overdue_days"] = row["days_since"] - int(cadence)
    else:
        row["overdue_days"] = None
    row["birthday_in"] = _days_to_birthday(row.get("birthday"))
    return row


def _days_to_birthday(value: str | None) -> int | None:
    """Bis zum nächsten Geburtstag. Auch ohne Jahrgang (--MM-DD)."""
    if not value:
        return None
    text = str(value)
    try:
        month, day = int(text[-5:-3]), int(text[-2:])
    except ValueError:
        return None
    today = date.today()
    try:
        this_year = date(today.year, month, day)
    except ValueError:                          # 29. Februar in einem Normaljahr
        this_year = date(today.year, month, 28)
    if this_year < today:
        try:
            this_year = date(today.year + 1, month, day)
        except ValueError:
            this_year = date(today.year + 1, month, 28)
    return (this_year - today).days


def update(person_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in FIELDS:
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if sets:
        values.append(person_id)
        with get_db() as db:
            db.execute(f"UPDATE people SET {', '.join(sets)} WHERE id=?", values)
    return get(person_id)


def delete(person_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM people WHERE id=?", (person_id,))


def query(active_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE active=1" if active_only else ""
    with get_db() as db:
        rows = db.execute(f"SELECT * FROM people {where} ORDER BY name").fetchall()
    return [_decorate(dict(r)) for r in rows]


def log_contact(person_id: int, what: str | None = None) -> dict[str, Any]:
    with get_db() as db:
        db.execute("INSERT INTO people_log(person_id, what) VALUES(?,?)",
                   (person_id, what))
        db.execute("UPDATE people SET last_contact=? WHERE id=?",
                   (today_str(), person_id))
    return get(person_id)


def history(person_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM people_log WHERE person_id=? ORDER BY id DESC LIMIT ?",
            (person_id, limit)).fetchall()
    return rows_to_dicts(rows)


def due() -> list[dict[str, Any]]:
    """Wer dran wäre — nach deinem eigenen Rhythmus, nicht nach Gefühl."""
    out = [p for p in query()
           if p.get("overdue_days") is not None and p["overdue_days"] >= 0]
    out.sort(key=lambda p: -(p["overdue_days"] or 0))
    return out


def birthdays(within_days: int = 30) -> list[dict[str, Any]]:
    out = [p for p in query()
           if p.get("birthday_in") is not None and p["birthday_in"] <= within_days]
    out.sort(key=lambda p: p["birthday_in"])
    return out
