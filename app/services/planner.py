"""Der Tagesplan.

Kompass darf selbst umplanen — das war die Ansage. Er tut es nach festen,
nachvollziehbaren Regeln und schreibt jede Veränderung ins Protokoll:

* Was gestern offen blieb, kommt auf heute. Kein Datum von vorgestern.
* Tägliche Routinen stehen immer drin, von den selteneren höchstens zwei —
  sonst wird aus jedem Dienstag ein Putztag und man fängt gar nicht erst an.
* Der Rest wird nach verfügbarer Zeit gefüllt, nicht nach Wunschdenken.
  Was nicht passt, steht offen sichtbar darunter statt heimlich im Plan.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from ..db import (get_db, get_setting, log_event, parse_day, today_str,
                  weekday_key)
from . import projects, routines, tasks

MAX_SLOW_ROUTINES = 2        # zusätzlich zu den täglichen
DAILY_INTERVAL = 2.0         # bis zu diesem Rhythmus gilt eine Routine als täglich


def capacity(day: str | None = None) -> int:
    """Wie viele Minuten du an diesem Wochentag realistisch hast."""
    key = weekday_key(parse_day(day) or date.today())
    try:
        table = json.loads(get_setting("capacity_json", "") or "{}")
    except ValueError:
        table = {}
    try:
        return int(table.get(key, 60))
    except (TypeError, ValueError):
        return 60


def set_capacity(table: dict[str, int]) -> None:
    from ..db import set_setting
    clean = {k: int(v) for k, v in table.items() if str(v).strip() != ""}
    set_setting("capacity_json", json.dumps(clean))


def plan(day: str | None = None) -> dict[str, Any]:
    """Den Tag zusammenstellen und die Auswahl festschreiben."""
    day = day or today_str()
    moved = tasks.roll_over(day)

    chosen_routines = _pick_routines(day)
    budget = capacity(day)
    used = sum(int(r["duration_min"] or 0) for r in chosen_routines)

    picked, overflow = _pick_tasks(day, max(0, budget - used))
    with get_db() as db:
        for task in picked:
            if task.get("planned_day") != day:
                db.execute("UPDATE tasks SET planned_day=? WHERE id=?", (day, task["id"]))
                task["planned_day"] = day
    used += sum(int(t["est_min"] or 0) for t in picked)

    if moved:
        log_event("plan", f"Tagesplan für {day} neu gelegt.")
    return {
        "day": day,
        "capacity_min": budget,
        "used_min": used,
        "moved": moved,
        "routines": chosen_routines,
        "tasks": picked,
        "overflow": overflow,
    }


def _pick_routines(day: str) -> list[dict[str, Any]]:
    due = routines.due(day)
    daily = [r for r in due if float(r["interval_days"] or 7) <= DAILY_INTERVAL]
    slow = [r for r in due if float(r["interval_days"] or 7) > DAILY_INTERVAL]
    slow.sort(key=lambda r: -(r.get("overdue_days") or 0))
    return daily + slow[:MAX_SLOW_ROUTINES]


def _pick_tasks(day: str, budget: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aufgaben in der Reihenfolge wählen, die im Alltag trägt."""
    open_tasks = tasks.query(status="open", limit=400)
    by_id: dict[int, dict[str, Any]] = {t["id"]: t for t in open_tasks}

    def bucket(task: dict[str, Any]) -> int:
        due = task.get("due_date")
        if due and due < day:
            return 0                                    # überfällig
        if due == day:
            return 1                                    # heute fällig
        if task.get("planned_day") == day:
            return 2                                    # war schon für heute geplant
        if task.get("project_id"):
            return 3                                    # bringt ein Projekt voran
        return 4                                        # der Rest

    ordered = sorted(
        by_id.values(),
        key=lambda t: (bucket(t), int(t.get("priority") or 2),
                       int(t.get("est_min") or 15), t["id"]))

    picked: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    left = budget
    seen_projects: set[int] = set()
    for task in ordered:
        minutes = int(task.get("est_min") or 15)
        pid = task.get("project_id")
        # Pro Projekt nur der nächste Schritt — der Rest wäre nur Ballast.
        if pid and pid in seen_projects and bucket(task) >= 3:
            overflow.append(task)
            continue
        if minutes <= left or bucket(task) == 0:
            picked.append(task)
            left -= minutes
            if pid:
                seen_projects.add(pid)
        else:
            overflow.append(task)
    return picked, overflow


def today(day: str | None = None) -> dict[str, Any]:
    """Der Tag, wie er gerade steht — ohne neu zu planen."""
    day = day or today_str()
    planned = [t for t in tasks.query(status="open", limit=400)
               if t.get("planned_day") == day
               or (t.get("due_date") and t["due_date"] <= day)]
    planned.sort(key=lambda t: (int(t.get("priority") or 2),
                                int(t.get("est_min") or 15)))
    due_routines = _pick_routines(day)
    done_today = [t for t in tasks.done_since(1) if t.get("done_at") == day]
    used = (sum(int(t["est_min"] or 0) for t in planned)
            + sum(int(r["duration_min"] or 0) for r in due_routines))
    return {
        "day": day,
        "capacity_min": capacity(day),
        "used_min": used,
        "tasks": planned,
        "routines": due_routines,
        "done": done_today,
        "slots": projects.slots(),
    }


def unplan(task_id: int) -> dict[str, Any]:
    """Aus dem heutigen Plan nehmen, ohne sie zu erledigen oder zu verlieren."""
    return tasks.update(task_id, {"planned_day": None})


def fits_summary(plan_data: dict[str, Any]) -> str:
    """Ein Satz, der die Lage beschreibt — taucht im Briefing auf."""
    used, budget = plan_data["used_min"], plan_data["capacity_min"]
    if not budget:
        return "Für heute ist keine Zeit hinterlegt."
    if used > budget:
        return (f"Der Plan ist {used - budget} Minuten zu voll — "
                f"{used} Minuten Arbeit bei {budget} Minuten Zeit.")
    return f"{used} von {budget} Minuten verplant."
