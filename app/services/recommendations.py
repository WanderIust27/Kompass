"""Empfehlungen — Bücher, Filme, Serien, Podcasts, Spiele.

Zwei Quellen: das lokale Modell, das deine Liste und deine Bewertungen
kennt, und — wenn Internet erlaubt ist — OpenLibrary beziehungsweise TMDB
fuer die harten Daten. Ohne Netz bleibt es beim Modellwissen, dann steht
das auch so dabei; erfundene Titel als echte Funde auszugeben wäre der
schlechteste Dienst.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..db import get_db, rows_to_dicts, today_str
from . import websearch
from .ollama_client import OllamaUnavailable, generate_json

log = logging.getLogger("kompass.empfehlungen")

KINDS = {"book": "Buch", "movie": "Film", "series": "Serie",
         "podcast": "Podcast", "game": "Spiel", "other": "Sonstiges"}

_SYSTEM = ("Du bist Kompass und empfiehlst Bücher, Filme, Serien und Spiele. "
           "Du kennst den Geschmack deines Gegenübers aus seiner Liste. Du "
           "empfiehlst nichts, was schon draufsteht. Du antwortest auf Deutsch "
           "und ausschließlich in dem verlangten JSON-Format.")


def create(data: dict[str, Any]) -> dict[str, Any]:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Ohne Titel geht es nicht.")
    kind = data.get("kind") if data.get("kind") in KINDS else "book"
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO recommendations(kind, title, creator, year, why, source,
                                           status, url, external_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (kind, title, data.get("creator"), data.get("year"), data.get("why"),
             data.get("source") or "ich", data.get("status") or "queued",
             data.get("url"),
             json.dumps(data["external"], ensure_ascii=False)
             if data.get("external") else None))
        new_id = cur.lastrowid
    return get(new_id)


def get(rec_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row:
        raise KeyError(f"Empfehlung {rec_id} gibt es nicht.")
    return dict(row)


def update(rec_id: int, data: dict[str, Any]) -> dict[str, Any]:
    sets, values = [], []
    for key in ("kind", "title", "creator", "year", "why", "status", "rating", "url"):
        if key in data:
            sets.append(f"{key}=?")
            values.append(data[key])
    if data.get("status") == "done":
        sets.append("done_at=?")
        values.append(today_str())
    if sets:
        values.append(rec_id)
        with get_db() as db:
            db.execute(f"UPDATE recommendations SET {', '.join(sets)} WHERE id=?", values)
    return get(rec_id)


def delete(rec_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM recommendations WHERE id=?", (rec_id,))


def query(kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if kind and kind != "alle":
        where.append("kind=?")
        args.append(kind)
    if status and status != "alle":
        where.append("status=?")
        args.append(status)
    with get_db() as db:
        rows = db.execute(
            f"""SELECT * FROM recommendations WHERE {' AND '.join(where)}
                ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'queued' THEN 1
                         ELSE 2 END, added_at DESC""", args).fetchall()
    return rows_to_dicts(rows)


def taste_profile() -> dict[str, Any]:
    """Was du gut fandest und was nicht — die Grundlage jeder Empfehlung."""
    with get_db() as db:
        liked = db.execute(
            "SELECT kind, title, creator, rating FROM recommendations "
            "WHERE rating>=4 ORDER BY rating DESC, done_at DESC LIMIT 15").fetchall()
        disliked = db.execute(
            "SELECT kind, title, creator, rating FROM recommendations "
            "WHERE rating<=2 ORDER BY rating LIMIT 8").fetchall()
        known = db.execute("SELECT title FROM recommendations LIMIT 200").fetchall()
    return {"mochtest": rows_to_dicts(liked), "nicht": rows_to_dicts(disliked),
            "bekannt": [r["title"] for r in known]}


def suggest(kind: str = "book", count: int = 4, hint: str | None = None) -> list[dict[str, Any]]:
    """Vorschläge holen — erst vom Modell, dann wenn möglich mit Daten belegen."""
    taste = taste_profile()
    liked = "; ".join(f"{r['title']} ({r['rating']}/5)" for r in taste["mochtest"]) or "—"
    disliked = "; ".join(r["title"] for r in taste["nicht"]) or "—"
    known = ", ".join(taste["bekannt"][:60]) or "—"
    label = KINDS.get(kind, "Buch")
    prompt = (
        f"Empfiehl {count} Titel der Sorte: {label}.\n"
        f"Gut gefallen haben: {liked}\n"
        f"Nicht gefallen haben: {disliked}\n"
        f"Schon auf der Liste (nicht nochmal vorschlagen): {known}\n"
        + (f"Zusätzlicher Wunsch: {hint}\n" if hint else "")
        + '\nAntworte als JSON: {"vorschläge": [{"titel": "...", "urheber": "...", '
          '"jahr": 2001, "warum": "ein Satz, warum das zu ihm passt"}]}')
    try:
        data = generate_json(prompt, system=_SYSTEM, temperature=0.8)
    except OllamaUnavailable as e:
        log.info("Keine Vorschläge möglich: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for item in (data.get("vorschläge") or [])[:count]:
        title = (item.get("titel") or "").strip()
        if not title:
            continue
        entry = {"kind": kind, "title": title, "creator": item.get("urheber"),
                 "year": item.get("jahr"), "why": item.get("warum"),
                 "source": "kompass", "verified": False}
        entry.update(_verify(title, kind))
        out.append(entry)
    return out


def _verify(title: str, kind: str) -> dict[str, Any]:
    """Gegen echte Daten prüfen, damit keine erfundenen Titel durchrutschen."""
    if not websearch.enabled():
        return {}
    try:
        if kind == "book":
            hits = websearch.openlibrary(title, limit=1)
        elif kind in ("movie", "series"):
            hits = websearch.tmdb(title, kind=kind, limit=1)
        else:
            hits = []
    except Exception as e:
        log.info("Abgleich fehlgeschlagen: %s", e)
        return {}
    if not hits:
        return {}
    hit = hits[0]
    same = (hit.get("title") or "").lower()[:20] == title.lower()[:20]
    return {"verified": bool(same), "url": hit.get("url"),
            "creator": hit.get("creator") or None,
            "year": hit.get("year")}


def lookup(title: str, kind: str = "book") -> list[dict[str, Any]]:
    """Direkte Suche in den externen Quellen — fuer das Eintragen von Hand."""
    if kind == "book":
        return websearch.openlibrary(title)
    if kind in ("movie", "series"):
        return websearch.tmdb(title, kind=kind)
    return []


def stats() -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM recommendations WHERE status='queued') AS liste,
                 (SELECT COUNT(*) FROM recommendations WHERE status='doing') AS gerade,
                 (SELECT COUNT(*) FROM recommendations WHERE status='done') AS durch,
                 (SELECT ROUND(AVG(rating),1) FROM recommendations
                    WHERE rating IS NOT NULL) AS schnitt""").fetchone()
    return dict(row)
