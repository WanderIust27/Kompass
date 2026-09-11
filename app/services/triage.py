"""Die Inbox — ein Feld fuer alles.

Der teuerste Moment beim Aufschreiben ist die Frage "wohin damit". Deshalb
gibt es genau ein Eingabefeld, und das Einsortieren passiert danach: das
Modell schlägt vor, du bestätigst mit einem Tippen. Wenn das Modell gerade
nicht erreichbar ist, übernimmt eine simple Worterkennung — die Inbox darf
nie blockieren.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..db import get_db, now_str, rows_to_dicts, today_str
from . import notes, people, projects, purchases, recommendations, routines, tasks
from .ollama_client import OllamaUnavailable, generate_json

log = logging.getLogger("kompass.inbox")

KINDS = ["aufgabe", "idee", "notiz", "kauf", "person", "empfehlung", "routine"]

_SYSTEM = (
    "Du sortierst kurze Zurufe eines Menschen mit ADHS in Schubladen ein. "
    "Du antwortest ausschließlich mit dem verlangten JSON, auf Deutsch, "
    "ohne Vorwort. Du erfindest keine Details, die nicht dastehen: Was nicht "
    "gesagt wurde, bleibt null.")

_PROMPT = """Zuruf: "{raw}"

Ordne ihn genau einer Art zu:
- aufgabe: etwas Konkretes, das erledigt werden muss
- idee: ein Einfall, ein Vorhaben, ein "man könnte mal" — alles, was nach
  einem neuen Projekt klingt
- notiz: etwas zum Merken, ohne Handlung
- kauf: er will etwas kaufen oder haben
- person: es geht um einen Menschen, Kontakt halten, Geburtstag
- empfehlung: ein Buch, Film, Serie, Podcast oder Spiel, das er sich merken will
- routine: etwas Wiederkehrendes im Haushalt

Antworte als JSON:
{{"art": "...",
  "titel": "kurz, in der Befehlsform bei Aufgaben",
  "notiz": "Zusatz oder null",
  "dauer_min": Zahl oder null,
  "energie": "niedrig|mittel|hoch" oder null,
  "kontext": "zuhause|laptop|unterwegs|telefon" oder null,
  "fällig": "YYYY-MM-DD" oder null,
  "preis": Zahl oder null,
  "sorte": "book|movie|series|podcast|game" oder null,
  "begründung": "ein Halbsatz, warum diese Schublade"}}"""


def add(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Leer reingeworfen ist auch nichts.")
    with get_db() as db:
        cur = db.execute("INSERT INTO inbox(raw) VALUES(?)", (raw,))
        inbox_id = cur.lastrowid
    return get(inbox_id)


def get(inbox_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM inbox WHERE id=?", (inbox_id,)).fetchone()
    if not row:
        raise KeyError(f"Inbox-Eintrag {inbox_id} gibt es nicht.")
    out = dict(row)
    if out.get("suggestion_json"):
        try:
            out["suggestion"] = json.loads(out["suggestion_json"])
        except ValueError:
            out["suggestion"] = None
    return out


def query(status: str = "new", limit: int = 100) -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if status and status != "alle":
        where.append("status=?")
        args.append(status)
    args.append(limit)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM inbox WHERE {' AND '.join(where)} "
            f"ORDER BY id DESC LIMIT ?", args).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if item.get("suggestion_json"):
            try:
                item["suggestion"] = json.loads(item["suggestion_json"])
            except ValueError:
                item["suggestion"] = None
        out.append(item)
    return out


def suggest(inbox_id: int) -> dict[str, Any]:
    """Vorschlag holen und merken, damit er beim Blättern schon dasteht."""
    item = get(inbox_id)
    guess = classify(item["raw"])
    with get_db() as db:
        db.execute("UPDATE inbox SET kind=?, suggestion_json=? WHERE id=?",
                   (guess.get("art"), json.dumps(guess, ensure_ascii=False), inbox_id))
    return get(inbox_id)


def classify(raw: str) -> dict[str, Any]:
    try:
        guess = generate_json(_PROMPT.format(raw=raw.replace('"', "'")),
                              system=_SYSTEM, temperature=0.2)
    except OllamaUnavailable as e:
        log.info("Kein Modell erreichbar (%s) — sortiere nach Stichworten.", e)
        return _fallback(raw)
    if guess.get("art") not in KINDS:
        guess["art"] = _fallback(raw)["art"]
    guess.setdefault("titel", raw[:80])
    if not (guess.get("titel") or "").strip():
        guess["titel"] = raw[:80]
    return guess


_BUY = re.compile(r"\b(kauf|kaufen|bestell|haben will|anschaff|brauche ein)", re.I)
_IDEA = re.compile(r"\b(idee|koennte man|könnte man|was waere wenn|was wäre wenn|vielleicht mal|projekt)", re.I)
_REC = re.compile(r"\b(buch|film|serie|podcast|anschauen|lesen|spiel)\b", re.I)
_ROUTINE = re.compile(r"\b(jeden|jede woche|taeglich|täglich|woechentlich|wöchentlich|regelmaessig|regelmäßig)\b", re.I)
_PRICE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:eur|euro|€)", re.I)


def _fallback(raw: str) -> dict[str, Any]:
    """Ohne Modell: grob, aber nie falsch genug, um zu schaden."""
    price = None
    match = _PRICE.search(raw)
    if match:
        price = float(match.group(1).replace(",", "."))
    if _BUY.search(raw) or price is not None:
        art = "kauf"
    elif _ROUTINE.search(raw):
        art = "routine"
    elif _IDEA.search(raw):
        art = "idee"
    elif _REC.search(raw):
        art = "empfehlung"
    else:
        art = "aufgabe"
    return {"art": art, "titel": raw.strip()[:80], "notiz": None, "preis": price,
            "dauer_min": None, "energie": None, "kontext": None, "fällig": None,
            "sorte": None, "begründung": "nach Stichworten einsortiert"}


def apply(inbox_id: int, kind: str | None = None,
          fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Vorschlag annehmen (oder korrigieren) und den echten Eintrag anlegen."""
    item = get(inbox_id)
    data = dict(item.get("suggestion") or {})
    if fields:
        data.update(fields)
    art = kind or data.get("art") or "aufgabe"
    title = (data.get("titel") or item["raw"]).strip()[:200]
    note = data.get("notiz")

    if art == "aufgabe":
        created = tasks.create({
            "title": title, "note": note,
            "est_min": data.get("dauer_min") or 15,
            "energy": data.get("energie") or "mittel",
            "context": data.get("kontext"),
            "due_date": data.get("fällig"),
            "project_id": data.get("project_id"),
        })
        target = ("task", created["id"])
    elif art == "idee":
        created = projects.add_idea(title, note)
        target = ("idea", created["id"])
    elif art == "notiz":
        created = notes.create({"title": title, "body": note or item["raw"]})
        target = ("note", created["id"])
    elif art == "kauf":
        created = purchases.create({"title": title, "price_eur": data.get("preis"),
                                    "reason": note, "url": data.get("url")})
        target = ("purchase", created["id"])
    elif art == "person":
        created = people.create({"name": title, "note": note})
        target = ("person", created["id"])
    elif art == "empfehlung":
        created = recommendations.create({"title": title, "kind": data.get("sorte") or "book",
                                          "why": note})
        target = ("recommendation", created["id"])
    elif art == "routine":
        created = routines.create({"title": title, "note": note,
                                   "interval_days": data.get("intervall") or 7,
                                   "duration_min": data.get("dauer_min") or 10,
                                   "energy": data.get("energie") or "mittel",
                                   "room": data.get("raum")})
        target = ("routine", created["id"])
    else:
        raise ValueError(f"Unbekannte Art: {art}")

    with get_db() as db:
        db.execute(
            "UPDATE inbox SET status='sorted', kind=?, target_kind=?, target_id=?, "
            "sorted_at=? WHERE id=?",
            (art, target[0], target[1], now_str(), inbox_id))
    return {"inbox": get(inbox_id), "created": created, "kind": art}


def dismiss(inbox_id: int) -> dict[str, Any]:
    with get_db() as db:
        db.execute("UPDATE inbox SET status='dismissed', sorted_at=? WHERE id=?",
                   (now_str(), inbox_id))
    return get(inbox_id)


def delete(inbox_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM inbox WHERE id=?", (inbox_id,))


def pending_count() -> int:
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) AS n FROM inbox WHERE status='new'").fetchone()
    return int(row["n"])


def sort_all(limit: int = 10) -> int:
    """Alles Unsortierte vom Modell einschätzen lassen — ohne es anzulegen."""
    todo = [i for i in query("new", limit) if not i.get("suggestion")]
    for item in todo:
        try:
            suggest(item["id"])
        except Exception as e:
            log.info("Konnte %s nicht einschätzen: %s", item["id"], e)
    return len(todo)
