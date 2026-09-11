"""Aufgaben — der Werkzeugkasten hinter dem Reiter 'Aufgaben'."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..db import (day_plus, get_db, log_event, parse_day, rows_to_dicts,
                  today_str)

AREAS = ["alltag", "haushalt", "projekt", "menschen", "admin"]
ENERGIES = ["niedrig", "mittel", "hoch"]
CONTEXTS = ["zuhause", "laptop", "unterwegs", "telefon"]

FIELDS = ("title", "note", "project_id", "area", "est_min", "energy", "context",
          "due_date", "planned_day", "priority", "sort_order", "status")


def create(data: dict[str, Any]) -> dict[str, Any]:
    row = {
        "title": (data.get("title") or "").strip(),
        "note": data.get("note"),
        "project_id": data.get("project_id"),
        "area": data.get("area") if data.get("area") in AREAS else "alltag",
        "est_min": int(data.get("est_min") or 15),
        "energy": data.get("energy") if data.get("energy") in ENERGIES else "mittel",
        "context": data.get("context"),
        "due_date": data.get("due_date") or None,
        "planned_day": data.get("planned_day") or None,
        "priority": int(data.get("priority") or 2),
        "routine_id": data.get("routine_id"),
    }
    if not row["title"]:
        raise ValueError("Eine Aufgabe braucht einen Titel.")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO tasks(title, note, project_id, area, est_min, energy,
                                 context, due_date, planned_day, priority, routine_id)
               VALUES(:title,:note,:project_id,:area,:est_min,:energy,:context,
                      :due_date,:planned_day,:priority,:routine_id)""", row)
        task_id = cur.lastrowid
    return get(task_id)


def get(task_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """SELECT t.*, p.title AS project_title
               FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
               WHERE t.id=?""", (task_id,)).fetchone()
    if not row:
        raise KeyError(f"Aufgabe {task_id} gibt es nicht.")
    return dict(row)


def update(task_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in FIELDS:
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if not sets:
        return get(task_id)
    values.append(task_id)
    with get_db() as db:
        db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", values)
    return get(task_id)


def complete(task_id: int, done: bool = True) -> dict[str, Any]:
    with get_db() as db:
        db.execute("UPDATE tasks SET status=?, done_at=? WHERE id=?",
                   ("done" if done else "open",
                    today_str() if done else None, task_id))
    return get(task_id)


def drop(task_id: int) -> None:
    with get_db() as db:
        db.execute("UPDATE tasks SET status='dropped' WHERE id=?", (task_id,))


def delete(task_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM tasks WHERE id=?", (task_id,))


def snooze(task_id: int, days: int = 1) -> dict[str, Any]:
    """Aufgabe verschieben. Wird mitgezaehlt — daraus lernt Kompass spaeter."""
    task = get(task_id)
    base = parse_day(task.get("planned_day")) or date.today()
    new_day = max(base + timedelta(days=days), date.today() + timedelta(days=days))
    with get_db() as db:
        db.execute("UPDATE tasks SET planned_day=?, snoozes=snoozes+1 WHERE id=?",
                   (new_day.isoformat(), task_id))
    return get(task_id)


def query(status: str = "open", area: str | None = None,
          project_id: int | None = None, day: str | None = None,
          energy: str | None = None, context: str | None = None,
          unplanned: bool = False, limit: int = 300) -> list[dict[str, Any]]:
    where = ["1=1"]
    args: list[Any] = []
    if status and status != "alle":
        where.append("t.status=?")
        args.append(status)
    if area:
        where.append("t.area=?")
        args.append(area)
    if project_id:
        where.append("t.project_id=?")
        args.append(project_id)
    if day:
        where.append("(t.planned_day=? OR (t.due_date IS NOT NULL AND t.due_date<=?))")
        args += [day, day]
    if energy:
        where.append("t.energy=?")
        args.append(energy)
    if context:
        where.append("t.context=?")
        args.append(context)
    if unplanned:
        where.append("t.planned_day IS NULL")
    args.append(limit)
    with get_db() as db:
        rows = db.execute(
            f"""SELECT t.*, p.title AS project_title
                FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
                WHERE {' AND '.join(where)}
                ORDER BY
                  CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
                  t.due_date, t.priority, t.sort_order, t.id
                LIMIT ?""", args).fetchall()
    return rows_to_dicts(rows)


def overdue(day: str | None = None) -> list[dict[str, Any]]:
    day = day or today_str()
    with get_db() as db:
        rows = db.execute(
            """SELECT t.*, p.title AS project_title
               FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
               WHERE t.status='open' AND t.due_date IS NOT NULL AND t.due_date < ?
               ORDER BY t.due_date, t.priority""", (day,)).fetchall()
    return rows_to_dicts(rows)


def roll_over(day: str | None = None) -> int:
    """Was gestern geplant war und offen blieb, kommt auf heute.

    Kompass macht das selbst und schreibt es ins Protokoll — sonst steht der
    Tagesplan mit Datum von vorgestern da und wirkt wie ein Vorwurf.
    """
    day = day or today_str()
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM tasks WHERE status='open' AND planned_day IS NOT NULL "
            "AND planned_day < ?", (day,)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            marks = ",".join("?" * len(ids))
            db.execute(
                f"UPDATE tasks SET planned_day=?, snoozes=snoozes+1 "
                f"WHERE id IN ({marks})", [day] + ids)
    if ids:
        log_event("plan", f"{len(ids)} offene Aufgabe(n) von gestern auf heute gezogen.")
    return len(ids)


def counts() -> dict[str, int]:
    with get_db() as db:
        row = db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM tasks WHERE status='open') AS offen,
                 (SELECT COUNT(*) FROM tasks WHERE status='open'
                    AND planned_day=date('now','localtime')) AS heute,
                 (SELECT COUNT(*) FROM tasks WHERE status='open'
                    AND due_date < date('now','localtime')) AS ueberfaellig,
                 (SELECT COUNT(*) FROM tasks WHERE status='done'
                    AND done_at=date('now','localtime')) AS heute_erledigt
            """).fetchone()
    return dict(row)


def done_since(days: int = 7) -> list[dict[str, Any]]:
    since = day_plus(-days)
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM tasks WHERE status='done' AND done_at>=? "
            "ORDER BY done_at DESC", (since,)).fetchall()
    return rows_to_dicts(rows)
