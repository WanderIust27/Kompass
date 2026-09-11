"""Der Anschub — ein eigener Kopf für den Moment, in dem nichts mehr geht.

Kompass plant, sortiert und bremst. Wenn aber alles gleich wichtig aussieht
und deshalb gar nichts passiert, hilft Planen nicht mehr: Noch eine Liste ist
dann genau das Problem. Deshalb übernimmt hier eine andere Stimme mit einer
einzigen Aufgabe — EIN Einstieg, klein genug, dass man ihn nicht verhandeln
kann, und die ausdrückliche Erlaubnis, alles andere liegen zu lassen.

Der Anschub darf ein eigenes Modell benutzen (Einstellung `unblock_model`),
weil es eine andere Art Antwort ist als ein Briefing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..db import get_db, get_int, get_setting, log_event, rows_to_dicts
from . import routines, tasks
from .ollama_client import OllamaUnavailable, generate_json

log = logging.getLogger("kompass.anschub")

PERSONA = """Du bist „Anschub“ — nicht Kompass, sondern der Kopf, der übernimmt,
wenn gar nichts mehr geht. Dein Gegenüber hat ADHS und steckt gerade fest: zu
viel auf einmal, alles gleich dringend, und deshalb passiert nichts.

Deine einzige Aufgabe ist EIN Einstieg. Kein Plan, keine drei Vorschläge.

Regeln, von denen du nicht abweichst:
- Der Schritt dauert höchstens fünf Minuten und ist körperlich konkret.
  „Stell die Tasse in die Spülmaschine“ — nicht „Küche aufräumen“.
- Du nimmst ihn aus dem, was wirklich ansteht. Du erfindest nichts dazu.
- Ein Halbsatz, warum ausgerechnet dieser. Keine Begründungskette.
- Du sagst ausdrücklich, was jetzt liegenbleiben darf. Die Erlaubnis ist die
  halbe Arbeit.
- Kein Mitleid, keine Motivationssprüche, keine Ausrufezeichen, kein Lob auf
  Vorrat. Ruhig und kurz.

Du antwortest ausschließlich mit dem verlangten JSON, auf Deutsch."""

_PROMPT = """Das steht gerade offen:
{candidates}

{feeling}Zustand: {state}

Antworte als JSON:
{{"schritt": "der eine konkrete Handgriff, höchstens fünf Minuten",
  "bezug": "task" oder "routine" oder "frei",
  "id": Zahl der passenden Sache oder null,
  "dauer_min": Zahl von 1 bis 5,
  "warum": "ein Halbsatz",
  "ignorieren": ["was jetzt ausdrücklich liegenbleiben darf", "höchstens drei"],
  "satz": "ein ruhiger Satz, der den Druck rausnimmt"}}"""


def model() -> str | None:
    return (get_setting("unblock_model", "") or "").strip() or None


# ------------------------------------------------------------------ Signale

def signals() -> dict[str, Any]:
    """Woran man Feststecken in den Daten sieht — gerechnet, nicht geraten."""
    with get_db() as db:
        row = db.execute("""SELECT
            (SELECT COUNT(*) FROM tasks WHERE status='done'
               AND done_at=date('now','localtime')) AS heute_fertig,
            (SELECT COUNT(*) FROM routine_log
               WHERE day=date('now','localtime')) AS heute_haushalt,
            (SELECT COUNT(*) FROM tasks WHERE status='open'
               AND planned_day=date('now','localtime')) AS heute_offen,
            (SELECT COUNT(*) FROM tasks WHERE status='open'
               AND due_date<date('now','localtime')) AS überfällig,
            (SELECT COUNT(*) FROM tasks WHERE status='open' AND snoozes>=3) AS klebt,
            (SELECT COUNT(*) FROM inbox WHERE status='new') AS inbox,
            (SELECT COUNT(*) FROM routines WHERE active=1
               AND next_due<date('now','localtime','-3 day')) AS haushalt_alt,
            (SELECT COUNT(*) FROM tasks WHERE status='done'
               AND done_at>=date('now','localtime','-3 day')) AS drei_tage_fertig
        """).fetchone()
    out = dict(row)
    out["stunde"] = datetime.now().hour
    return out


def nudge() -> dict[str, Any] | None:
    """Der eine Satz, der ungefragt auf der Startseite steht — oder gar keiner.

    Bewusst höchstens einer: Drei Hinweise auf einmal sind wieder eine Liste,
    und Listen sind das, woran es gerade scheitert.
    """
    s = signals()
    offen = s["heute_offen"] + s["überfällig"]
    hour = get_int("nudge_hour", 14)

    if s["drei_tage_fertig"] == 0 and offen >= 2:
        return {"grund": "drei_tage",
                "text": "Seit drei Tagen ist nichts abgehakt. Das ist keine "
                        "Faulheit, das ist Feststecken — ich such dir einen Einstieg."}
    if s["stunde"] >= hour and (s["heute_fertig"] + s["heute_haushalt"]) == 0 and offen >= 2:
        return {"grund": "heute_nichts",
                "text": f"Es ist {s['stunde']} Uhr und heute ist noch nichts gelaufen. "
                        f"Fangen wir klein an."}
    if s["klebt"] >= 3:
        return {"grund": "klebt",
                "text": f"{s['klebt']} Sachen schiebst du seit Tagen vor dir her. "
                        f"Meistens ist eine davon der Stöpsel."}
    if s["haushalt_alt"] >= 5:
        return {"grund": "haushalt",
                "text": f"{s['haushalt_alt']} Haushaltssachen sind seit über drei "
                        f"Tagen offen. Das wächst nur weiter."}
    if s["inbox"] >= 8:
        return {"grund": "inbox",
                "text": f"{s['inbox']} Zurufe liegen unsortiert. Das im Kopf zu "
                        f"behalten kostet mehr Kraft als das Einsortieren."}
    return None


# ------------------------------------------------------------------ Einstieg

def candidates(limit: int = 14) -> list[dict[str, Any]]:
    """Was überhaupt infrage kommt. Kleines zuerst — darum geht es hier."""
    out: list[dict[str, Any]] = []
    for t in tasks.query(status="open", limit=80):
        out.append({"kind": "task", "id": t["id"], "title": t["title"],
                    "min": int(t.get("est_min") or 15),
                    "note": t.get("note"), "snoozes": int(t.get("snoozes") or 0)})
    for r in routines.due():
        out.append({"kind": "routine", "id": r["id"], "title": r["title"],
                    "min": int(r.get("duration_min") or 10),
                    "note": r.get("room"), "snoozes": int(r.get("skips") or 0)})
    out.sort(key=lambda c: (c["min"], -c["snoozes"]))
    return out[:limit]


def rescue(feeling: str | None = None) -> dict[str, Any]:
    """Einen Einstieg holen und festhalten, was vorgeschlagen wurde."""
    options = candidates()
    state = signals()
    result = _ask(options, state, feeling) if options else None
    if result is None:
        result = _fallback(options)

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO unblock_log(feeling, signals_json, step, kind, ref_id,
                                       minutes, why, ignore_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (feeling, json.dumps(state, ensure_ascii=False), result["schritt"],
             result.get("bezug"), result.get("id"), result.get("dauer_min"),
             result.get("warum"),
             json.dumps(result.get("ignorieren") or [], ensure_ascii=False)))
        result["id_log"] = cur.lastrowid
    return result


def _ask(options: list[dict[str, Any]], state: dict[str, Any],
         feeling: str | None) -> dict[str, Any] | None:
    lines = "\n".join(
        f"- [{c['kind']} {c['id']}] {c['title']} ({c['min']} min"
        + (f", schon {c['snoozes']}× verschoben" if c["snoozes"] >= 2 else "") + ")"
        for c in options)
    said = f'Er sagt: "{feeling.strip()}"\n\n' if (feeling or "").strip() else ""
    zustand = (f"{state['heute_fertig'] + state['heute_haushalt']} Sachen heute "
               f"erledigt, {state['überfällig']} überfällig, "
               f"{state['klebt']} kleben seit Tagen.")
    try:
        data = generate_json(
            _PROMPT.format(candidates=lines, feeling=said, state=zustand),
            system=PERSONA, temperature=0.5, model=model())
    except OllamaUnavailable as e:
        log.info("Anschub ohne Modell (%s).", e)
        return None
    step = (data.get("schritt") or "").strip()
    if not step:
        return None
    ignore = data.get("ignorieren")
    return {
        "schritt": step,
        "bezug": data.get("bezug") if data.get("bezug") in ("task", "routine") else "frei",
        "id": data.get("id") if isinstance(data.get("id"), int) else None,
        "dauer_min": min(15, max(1, int(data.get("dauer_min") or 5))),
        "warum": (data.get("warum") or "").strip() or None,
        "ignorieren": [str(i) for i in ignore][:3] if isinstance(ignore, list) else [],
        "satz": (data.get("satz") or "").strip() or None,
        "gerechnet": False,
    }


def _fallback(options: list[dict[str, Any]]) -> dict[str, Any]:
    """Ohne Modell: das Kleinste, was offen ist. Auch das ist ein Einstieg."""
    if not options:
        return {"schritt": "Zwei Minuten aufräumen, was gerade vor dir liegt.",
                "bezug": "frei", "id": None, "dauer_min": 2,
                "warum": "Es steht nichts an — dann fängst du mit dem an, was du siehst.",
                "ignorieren": [], "satz": "Heute ist nichts offen. Wirklich.",
                "gerechnet": True}
    first = options[0]
    rest = len(options) - 1
    return {
        "schritt": first["title"],
        "bezug": first["kind"], "id": first["id"],
        "dauer_min": min(5, first["min"]),
        "warum": "Es ist das Kleinste, was offen ist.",
        "ignorieren": [f"die anderen {rest} Sachen für die nächsten "
                       f"{min(5, first['min'])} Minuten"] if rest else [],
        "satz": "Nur das. Danach darfst du aufhören.",
        "gerechnet": True,
    }


def outcome(log_id: int, verdict: str) -> dict[str, Any]:
    """geschafft | anders | nichts — daraus wird die Trefferquote des Anschubs."""
    with get_db() as db:
        db.execute("UPDATE unblock_log SET outcome=? WHERE id=?", (verdict, log_id))
        row = db.execute("SELECT * FROM unblock_log WHERE id=?", (log_id,)).fetchone()
    if verdict == "geschafft":
        log_event("anschub", "Einstieg hat geklappt.")
    return dict(row) if row else {}


def stats() -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """SELECT COUNT(*) AS gesamt,
                      SUM(CASE WHEN outcome='geschafft' THEN 1 ELSE 0 END) AS geschafft,
                      SUM(CASE WHEN outcome='nichts' THEN 1 ELSE 0 END) AS nichts
               FROM unblock_log""").fetchone()
    out = {k: int(v or 0) for k, v in dict(row).items()}
    beantwortet = out["geschafft"] + out["nichts"]
    out["quote"] = round(out["geschafft"] / beantwortet * 100) if beantwortet else None
    return out


def history(limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM unblock_log ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)
