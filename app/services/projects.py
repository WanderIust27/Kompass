"""Ideen und Projekte — die Bremse.

Der Ablauf, auf den sich alles hier zurückführen lässt:

    reingeworfen  ->  Parkplatz (Karenzzeit)  ->  reif  ->  Ritual  ->  Projekt

Zwei Regeln machen die Arbeit: Eine Idee darf während der Karenz nicht
gestartet werden, und es dürfen nur wenige Projekte gleichzeitig laufen.
Beides ist in den Einstellungen veränderbar; das Limit lässt sich mit
Begründung brechen, und die Begründung wird aufgehoben.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..db import (day_plus, get_db, get_int, log_event, parse_day,
                  rows_to_dicts, today_str)

RITUAL_QUESTIONS = [
    ("outcome", "Woran merkst du, dass es fertig ist?"),
    ("hours", "Wie viele Stunden kostet das realistisch — mal zwei gerechnet?"),
    ("instead", "Was bleibt dafuer liegen?"),
    ("why_now", "Warum jetzt und nicht in drei Monaten?"),
]


# ------------------------------------------------------------------- Ideen

def cooldown_days() -> int:
    return get_int("idea_cooldown_days", 7)


def wip_limit() -> int:
    return get_int("wip_limit", 3)


def add_idea(title: str, note: str | None = None,
             cooldown: int | None = None) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("Eine Idee braucht einen Titel.")
    days = cooldown if cooldown is not None else cooldown_days()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO ideas(title, note, ripe_at) VALUES(?,?,?)",
            (title, note, day_plus(days)))
        idea_id = cur.lastrowid
    return get_idea(idea_id)


def get_idea(idea_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    if not row:
        raise KeyError(f"Idee {idea_id} gibt es nicht.")
    return _decorate_idea(dict(row))


def _decorate_idea(row: dict[str, Any]) -> dict[str, Any]:
    ripe = parse_day(row.get("ripe_at"))
    row["days_left"] = max(0, (ripe - date.today()).days) if ripe else 0
    row["is_ripe"] = bool(ripe and ripe <= date.today())
    return row


def ideas(status: str | None = None) -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if status and status != "alle":
        where.append("status=?")
        args.append(status)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM ideas WHERE {' AND '.join(where)} "
            f"ORDER BY ripe_at, id DESC", args).fetchall()
    return [_decorate_idea(dict(r)) for r in rows]


def ripen() -> int:
    """Karenzzeiten ablaufen lassen. Läuft täglich im Hintergrund."""
    with get_db() as db:
        cur = db.execute(
            "UPDATE ideas SET status='ripe' WHERE status='parked' AND ripe_at<=?",
            (today_str(),))
        count = cur.rowcount or 0
    if count:
        log_event("ideen", f"{count} Idee(n) sind aus der Karenz — jetzt entscheiden.")
    return count


def update_idea(idea_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in ("title", "note", "status", "ripe_at", "review_json", "ai_take"):
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if sets:
        values.append(idea_id)
        with get_db() as db:
            db.execute(f"UPDATE ideas SET {', '.join(sets)} WHERE id=?", values)
    return get_idea(idea_id)


def drop_idea(idea_id: int) -> dict[str, Any]:
    with get_db() as db:
        db.execute("UPDATE ideas SET status='dropped', decided_at=? WHERE id=?",
                   (today_str(), idea_id))
    return get_idea(idea_id)


def sleep_idea(idea_id: int, days: int = 30) -> dict[str, Any]:
    """Nochmal schlafen legen statt entscheiden. Zählt mit."""
    with get_db() as db:
        db.execute(
            "UPDATE ideas SET status='parked', ripe_at=?, revived=revived+1 WHERE id=?",
            (day_plus(days), idea_id))
    return get_idea(idea_id)


def delete_idea(idea_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM ideas WHERE id=?", (idea_id,))


# ----------------------------------------------------------------- Projekte

def active_count() -> int:
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) AS n FROM projects WHERE status='active'"
                         ).fetchone()
    return int(row["n"])


def slots() -> dict[str, int]:
    limit = wip_limit()
    used = active_count()
    return {"limit": limit, "used": used, "free": max(0, limit - used)}


def add_project(title: str, why: str | None = None, deadline: str | None = None,
                next_action: str | None = None, from_idea_id: int | None = None,
                override_reason: str | None = None) -> dict[str, Any]:
    """Projekt starten. Ueber dem Limit nur mit Begründung."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Ein Projekt braucht einen Titel.")
    state = slots()
    if state["free"] <= 0 and not override_reason:
        raise PermissionError(
            f"Du hast schon {state['used']} von {state['limit']} Projekten laufen. "
            f"Schließ eines ab oder leg eines auf Eis — oder sag, warum dieses "
            f"wichtiger ist als die laufenden.")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO projects(title, why, deadline, next_action, started_at,
                                    from_idea_id, override_reason)
               VALUES(?,?,?,?,?,?,?)""",
            (title, why, deadline, next_action, today_str(), from_idea_id,
             override_reason))
        project_id = cur.lastrowid
        if from_idea_id:
            db.execute(
                "UPDATE ideas SET status='promoted', project_id=?, decided_at=? "
                "WHERE id=?", (project_id, today_str(), from_idea_id))
    if override_reason:
        log_event("projekte",
                  f"WIP-Limit gebrochen fuer „{title}“ — Begründung: {override_reason}")
    else:
        log_event("projekte", f"Projekt „{title}“ gestartet.")
    return get_project(project_id)


def get_project(project_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise KeyError(f"Projekt {project_id} gibt es nicht.")
        counts = db.execute(
            """SELECT COUNT(*) AS gesamt,
                      SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS erledigt,
                      SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS offen
               FROM tasks WHERE project_id=?""", (project_id,)).fetchone()
    out = dict(row)
    out["tasks"] = {k: int(v or 0) for k, v in dict(counts).items()}
    return out


def projects(status: str | None = "active") -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if status and status != "alle":
        where.append("p.status=?")
        args.append(status)
    with get_db() as db:
        rows = db.execute(
            f"""SELECT p.*,
                  (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id
                     AND t.status='open') AS open_tasks,
                  (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id
                     AND t.status='done') AS done_tasks,
                  (SELECT MAX(done_at) FROM tasks t WHERE t.project_id=p.id
                     AND t.status='done') AS last_progress
                FROM projects p WHERE {' AND '.join(where)}
                ORDER BY (p.deadline IS NULL), p.deadline, p.id DESC""",
            args).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        last = parse_day(row.get("last_progress") or row.get("started_at"))
        row["stale_days"] = (date.today() - last).days if last else None
        out.append(row)
    return out


def update_project(project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in ("title", "why", "status", "deadline", "next_action", "note"):
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if data.get("status") == "done":
        sets.append("done_at=?")
        values.append(today_str())
    if sets:
        values.append(project_id)
        with get_db() as db:
            db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", values)
    return get_project(project_id)


def delete_project(project_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))


def stale(days: int = 14) -> list[dict[str, Any]]:
    """Projekte, an denen lange nichts passiert ist — Stoff fuer den Wochenrückblick."""
    return [p for p in projects("active")
            if p.get("stale_days") is not None and p["stale_days"] >= days]


# ------------------------------------------------------------------ Ritual

def review(idea_id: int, answers: dict[str, str]) -> dict[str, Any]:
    """Das Bewertungsritual: vier Fragen, dann eine ehrliche Einschätzung.

    Die Fragen sind absichtlich unbequem. Wer sie beantwortet, hat die
    halbe Entscheidung schon getroffen — das Modell sagt danach nur noch,
    was es in den Antworten sieht.
    """
    import json as _json
    import logging as _logging

    from .ollama_client import OllamaUnavailable, generate

    log = _logging.getLogger("kompass.ideen")
    idea = get_idea(idea_id)
    with get_db() as db:
        db.execute("UPDATE ideas SET review_json=? WHERE id=?",
                   (_json.dumps(answers, ensure_ascii=False), idea_id))

    state = slots()
    running = ", ".join(p["title"] for p in projects("active")) or "keine"
    lines = [f"{label} — {answers.get(key, '(keine Antwort)')}"
             for key, label in RITUAL_QUESTIONS]
    prompt = (
        f"Idee: {idea['title']}\n"
        f"Notiz dazu: {idea.get('note') or '—'}\n"
        f"Sie liegt seit {idea['created_at'][:10]} auf dem Parkplatz.\n"
        f"Laufende Projekte ({state['used']} von {state['limit']}): {running}\n\n"
        + "\n".join(lines)
        + "\n\nSag in drei bis fuenf Sätzen, was du davon hältst: Ist das ein "
          "Projekt oder ein Impuls? Passt es neben das, was schon läuft? Wenn "
          "kein Platz frei ist, sag klar, was dafuer weichen müsste. Keine "
          "Aufzählung, kein Vorwort.")
    system = (
        "Du bist Kompass, der Assistent eines Menschen mit ADHS. Bei neuen Ideen "
        "bist du der Freund, der schon dreimal zugesehen hat, wie etwas nach zwei "
        "Wochen liegen blieb — wohlwollend, aber nicht naiv. Du redest ihm nichts "
        "aus, was trägt, und redest ihm nichts ein, was nicht trägt. Deutsch, "
        "knapp, du duzt.")
    take = None
    try:
        take = generate(prompt, system=system, temperature=0.5)
    except OllamaUnavailable as e:
        log.info("Keine Einschätzung möglich: %s", e)
    if take:
        with get_db() as db:
            db.execute("UPDATE ideas SET ai_take=? WHERE id=?", (take, idea_id))
    return get_idea(idea_id)


def promote(idea_id: int, override_reason: str | None = None,
            deadline: str | None = None, next_action: str | None = None) -> dict[str, Any]:
    """Aus einer reifen Idee ein Projekt machen — wenn ein Platz frei ist."""
    idea = get_idea(idea_id)
    if not idea["is_ripe"] and idea["status"] == "parked":
        raise PermissionError(
            f"Die Idee liegt noch {idea['days_left']} Tag(e) in der Karenz. "
            f"Das ist der Sinn der Sache.")
    return add_project(idea["title"], why=idea.get("note"), deadline=deadline,
                       next_action=next_action, from_idea_id=idea_id,
                       override_reason=override_reason)
