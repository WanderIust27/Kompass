"""Morgenbriefing und Abend-Check-in.

Das Briefing ist kein Bericht, sondern ein Anfang: Es soll das Aufstehen in
den Tag hinein leichter machen und nicht wie eine Mahnliste wirken. Deshalb
steht der nächste konkrete Schritt vorn, und alles Überfällige wird
benannt statt beschwiegen — aber nur einmal.

Wenn das Modell nicht erreichbar ist, gibt es trotzdem ein Briefing. Dann
eben eines, das Kompass selbst zusammenrechnet.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..db import (get_db, get_setting, parse_day, rows_to_dicts, today_str,
                  weekday_key)
from . import (people, planner, profile, projects, purchases, routines, tasks,
               triage)
from .ollama_client import OllamaUnavailable, generate

log = logging.getLogger("kompass.briefing")

WEEKDAY_NAMES = {"Mo": "Montag", "Di": "Dienstag", "Mi": "Mittwoch",
                 "Do": "Donnerstag", "Fr": "Freitag", "Sa": "Samstag",
                 "So": "Sonntag"}

TONES = {
    "direkt": "Du sagst klar und ohne Umschweife, was ansteht. Kein Aufmuntern, "
              "kein Schönreden, aber auch kein Vorwurf.",
    "freundlich": "Du bist warm und ermutigend, ohne ins Schwärmen zu geraten.",
    "trocken": "Du bist knapp und trocken, mit gelegentlichem, unaufdringlichem Witz.",
}


def system_prompt() -> str:
    tone = TONES.get(get_setting("tone", "direkt") or "direkt", TONES["direkt"])
    name = (get_setting("user_name", "") or "").strip()
    who = f" Er heißt {name}." if name else ""
    return (
        "Du bist Kompass, der persönliche Assistent eines Menschen mit ADHS." + who +
        " Du kennst seinen Alltag aus den Daten, die dir gegeben werden, und "
        "erfindest nichts dazu. " + tone +
        " Du duzt. Du schreibst Deutsch, in ganzen Sätzen, ohne Ueberschriften, "
        "ohne Aufzählungszeichen, ohne Emojis und ohne Vorwort wie 'Hier ist'. "
        "Du weißt, dass zu viele Punkte auf einmal lahmlegen: Du nennst höchstens "
        "drei Dinge und sagst, womit angefangen wird.")


def context(day: str | None = None) -> dict[str, Any]:
    """Alles, was fuer heute zählt — einmal eingesammelt."""
    day = day or today_str()
    state = planner.today(day)
    ideas_ripe = [i for i in projects.ideas("ripe")]
    ready_buys = purchases.query("ready")
    return {
        "tag": day,
        "wochentag": WEEKDAY_NAMES.get(weekday_key(parse_day(day)), ""),
        "plan": state,
        "überfällig": tasks.overdue(day),
        "inbox": triage.pending_count(),
        "ideen_reif": ideas_ripe,
        "projekte": projects.projects("active"),
        "slots": projects.slots(),
        "kaeufe_entscheiden": ready_buys,
        "kaeufe_warten": len(purchases.query("waiting")),
        "budget": purchases.budget_state(),
        "nutzung_fragen": purchases.usage_due(),
        "menschen_faellig": people.due()[:3],
        "geburtstage": people.birthdays(14),
        "haushalt": routines.stats(),
        "aufgaben": tasks.counts(),
        "gestern": _yesterday(day),
        "muster": profile.facts(),
    }


def _yesterday(day: str) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM checkins WHERE day=date(?, '-1 day')", (day,)).fetchone()
        done = db.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE status='done' "
            "AND done_at=date(?, '-1 day')", (day,)).fetchone()
    return {"checkin": dict(row) if row else None, "erledigt": int(done["n"])}


def _digest(ctx: dict[str, Any]) -> str:
    """Der Zustand in Klartext — das ist, was das Modell zu sehen bekommt."""
    plan = ctx["plan"]
    lines = [f"Datum: {ctx['wochentag']}, {ctx['tag']}",
             f"Zeit heute: {plan['capacity_min']} Minuten, verplant sind "
             f"{plan['used_min']}."]
    if plan["tasks"]:
        lines.append("Aufgaben heute: " + "; ".join(
            f"{t['title']} ({t['est_min']} min"
            + (f", fällig {t['due_date']}" if t.get("due_date") else "") + ")"
            for t in plan["tasks"][:8]))
    else:
        lines.append("Aufgaben heute: keine geplant.")
    if plan["routines"]:
        lines.append("Haushalt fällig: " + "; ".join(
            f"{r['title']} ({r['duration_min']} min"
            + (f", seit {r['overdue_days']} Tagen überfällig"
               if (r.get("overdue_days") or 0) > 0 else "") + ")"
            for r in plan["routines"]))
    if ctx["überfällig"]:
        lines.append(f"Überfällig: " + "; ".join(
            f"{t['title']} (seit {t['due_date']})" for t in ctx["überfällig"][:5]))
    if ctx["inbox"]:
        lines.append(f"Unsortiert in der Inbox: {ctx['inbox']}")
    if ctx["ideen_reif"]:
        lines.append("Ideen aus der Karenz (Entscheidung fällig): " + "; ".join(
            i["title"] for i in ctx["ideen_reif"][:5]))
    slots = ctx["slots"]
    lines.append(f"Projekte: {slots['used']} von {slots['limit']} Plätzen belegt."
                 + ("" if not ctx["projekte"] else " Laufend: " + "; ".join(
                     f"{p['title']}"
                     + (f" (seit {p['stale_days']} Tagen nichts passiert)"
                        if (p.get("stale_days") or 0) >= 10 else "")
                     for p in ctx["projekte"])))
    if ctx["kaeufe_entscheiden"]:
        lines.append("Wartefrist vorbei, Entscheidung fällig: " + "; ".join(
            f"{p['title']} ({p.get('price_eur') or '?'} Euro)"
            for p in ctx["kaeufe_entscheiden"][:4]))
    budget = ctx["budget"]
    if budget.get("budget"):
        lines.append(f"Budget diesen Monat: {budget['spent']:.0f} von "
                     f"{budget['budget']:.0f} Euro ausgegeben.")
    if ctx["geburtstage"]:
        lines.append("Geburtstage: " + "; ".join(
            f"{p['name']} in {p['birthday_in']} Tagen" for p in ctx["geburtstage"][:3]))
    if ctx["menschen_faellig"]:
        lines.append("Lange nicht gemeldet: " + "; ".join(
            f"{p['name']} (seit {p['days_since']} Tagen)"
            for p in ctx["menschen_faellig"]))
    if ctx["gestern"]["erledigt"]:
        lines.append(f"Gestern erledigt: {ctx['gestern']['erledigt']} Aufgabe(n).")
    if ctx["muster"]:
        lines.append("Was du über ihn weißt: " + " ".join(
            f["text"] for f in ctx["muster"][:4]))
    return "\n".join(lines)


def morning(day: str | None = None, force: bool = False) -> dict[str, Any]:
    day = day or today_str()
    existing = _stored(day, "morning")
    if existing and not force:
        return existing
    planner.plan(day)
    ctx = context(day)
    prompt = (_digest(ctx) + "\n\n"
              "Schreib das Morgenbriefing: vier bis sechs Sätze. Fang mit dem "
              "einen Ding an, mit dem er heute anfangen soll, und sag warum "
              "ausgerechnet damit. Nenn danach höchstens zwei weitere Punkte. "
              "Wenn der Plan zu voll ist, sag es und schlag vor, was wegfällt.")
    text = _ask(prompt) or _fallback_morning(ctx)
    return _store(day, "morning", text)


def evening(day: str | None = None, force: bool = False) -> dict[str, Any]:
    day = day or today_str()
    existing = _stored(day, "evening")
    if existing and not force:
        return existing
    ctx = context(day)
    done = ctx["plan"]["done"]
    prompt = (_digest(ctx) + "\n"
              + f"Heute erledigt: {len(done)} Aufgabe(n)"
              + (": " + "; ".join(t["title"] for t in done[:6]) if done else "")
              + "\n\nSchreib den Abend-Check-in: drei bis fuenf Sätze. Erst was "
                "heute lief — ehrlich, ohne Lob auf Vorrat. Dann, was auf morgen "
                "rutscht. Schließ mit genau einer Frage, die er in einem Satz "
                "beantworten kann.")
    text = _ask(prompt) or _fallback_evening(ctx)
    return _store(day, "evening", text)


def _ask(prompt: str) -> str | None:
    try:
        return generate(prompt, system=system_prompt(), temperature=0.6)
    except OllamaUnavailable as e:
        log.info("Briefing ohne Modell (%s).", e)
        return None


def _fallback_morning(ctx: dict[str, Any]) -> str:
    plan = ctx["plan"]
    parts = [f"{ctx['wochentag']}, {plan['capacity_min']} Minuten eingeplant."]
    first = (plan["tasks"] or plan["routines"] or [None])[0]
    if first:
        title = first.get("title")
        minutes = first.get("est_min") or first.get("duration_min")
        parts.append(f"Fang mit „{title}“ an — {minutes} Minuten.")
    else:
        parts.append("Nichts steht an. Wenn dir etwas einfällt, wirf es in die Inbox.")
    if ctx["überfällig"]:
        parts.append(f"{len(ctx['überfällig'])} Aufgabe(n) sind überfällig.")
    if ctx["ideen_reif"]:
        parts.append(f"{len(ctx['ideen_reif'])} Idee(n) warten auf eine Entscheidung.")
    if ctx["kaeufe_entscheiden"]:
        parts.append(f"{len(ctx['kaeufe_entscheiden'])} Kauf/Käufe haben die "
                     f"Wartefrist hinter sich.")
    parts.append("(Das Modell war gerade nicht erreichbar — das hier ist gerechnet, "
                 "nicht geschrieben.)")
    return " ".join(parts)


def _fallback_evening(ctx: dict[str, Any]) -> str:
    done = len(ctx["plan"]["done"])
    open_left = len(ctx["plan"]["tasks"])
    return (f"Heute sind {done} Aufgabe(n) fertig geworden, {open_left} stehen noch "
            f"offen und rutschen auf morgen. Haushalt: {ctx['haushalt']['fällig']} "
            f"Punkt(e) fällig. Was hat heute am meisten gebremst? "
            f"(Das Modell war nicht erreichbar — das hier ist gerechnet.)")


def _stored(day: str, slot: str) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM briefings WHERE day=? AND slot=?",
                         (day, slot)).fetchone()
    return dict(row) if row else None


def _store(day: str, slot: str, text: str) -> dict[str, Any]:
    with get_db() as db:
        db.execute(
            """INSERT INTO briefings(day, slot, text) VALUES(?,?,?)
               ON CONFLICT(day, slot) DO UPDATE SET text=excluded.text,
                 created_at=datetime('now')""", (day, slot, text))
    return _stored(day, slot) or {"day": day, "slot": slot, "text": text}


def recent(limit: int = 10) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM briefings ORDER BY day DESC, slot LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)


def save_checkin(data: dict[str, Any]) -> dict[str, Any]:
    """Der Abend-Check-in: zwei Regler, ein Satz. Mehr würde keiner ausfüllen."""
    day = data.get("day") or today_str()
    state = planner.today(day)
    with get_db() as db:
        db.execute(
            """INSERT INTO checkins(day, mood, energy, note, planned_count, done_count)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(day) DO UPDATE SET mood=excluded.mood,
                 energy=excluded.energy, note=excluded.note,
                 planned_count=excluded.planned_count, done_count=excluded.done_count""",
            (day, data.get("mood"), data.get("energy"), data.get("note"),
             len(state["tasks"]), len(state["done"])))
        row = db.execute("SELECT * FROM checkins WHERE day=?", (day,)).fetchone()
    return dict(row)


def checkins(limit: int = 30) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM checkins ORDER BY day DESC LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)
