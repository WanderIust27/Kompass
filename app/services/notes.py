"""Notizen — Volltext plus semantische Suche.

Zwei Wege zum selben Ziel: FTS5 findet Wörter zuverlässig und sofort,
die Vektorsuche findet, was du anders formuliert hast. Die Ergebnisse
werden zusammengeführt, damit man nicht raten muss, welche Suche gerade
die richtige gewesen wäre.
"""
from __future__ import annotations

import logging
from typing import Any

from ..db import get_db, get_setting, now_str, rows_to_dicts
from .ollama_client import (OllamaUnavailable, embed, embed_model, pack_vector,
                            unpack_vector)

log = logging.getLogger("kompass.notizen")


def _embeddings_on() -> bool:
    return (get_setting("embed_enabled", "1") == "1") and bool(embed_model())


def create(data: dict[str, Any]) -> dict[str, Any]:
    body = (data.get("body") or "").strip()
    if not body:
        raise ValueError("Eine Notiz ohne Text bringt nichts.")
    title = (data.get("title") or "").strip() or _title_from(body)
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO notes(title, body, tags, project_id) VALUES(?,?,?,?)",
            (title, body, data.get("tags"), data.get("project_id")))
        note_id = cur.lastrowid
        db.execute("INSERT INTO notes_fts(rowid, title, body) VALUES(?,?,?)",
                   (note_id, title, body))
    _embed_one(note_id, title, body)
    return get(note_id)


def _title_from(body: str) -> str:
    first = body.strip().splitlines()[0]
    return first[:70] + ("…" if len(first) > 70 else "")


def get(note_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if not row:
        raise KeyError(f"Notiz {note_id} gibt es nicht.")
    return dict(row)


def update(note_id: int, data: dict[str, Any]) -> dict[str, Any]:
    current = get(note_id)
    title = data.get("title", current["title"])
    body = data.get("body", current["body"])
    with get_db() as db:
        db.execute(
            "UPDATE notes SET title=?, body=?, tags=?, project_id=?, pinned=?, "
            "updated_at=? WHERE id=?",
            (title, body, data.get("tags", current["tags"]),
             data.get("project_id", current["project_id"]),
             int(data.get("pinned", current["pinned"]) or 0), now_str(), note_id))
        db.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))
        db.execute("INSERT INTO notes_fts(rowid, title, body) VALUES(?,?,?)",
                   (note_id, title, body))
        db.execute("DELETE FROM note_vectors WHERE note_id=?", (note_id,))
    _embed_one(note_id, title, body)
    return get(note_id)


def delete(note_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        db.execute("DELETE FROM notes_fts WHERE rowid=?", (note_id,))
        db.execute("DELETE FROM note_vectors WHERE note_id=?", (note_id,))


def recent(limit: int = 50, project_id: int | None = None) -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if project_id:
        where.append("project_id=?")
        args.append(project_id)
    args.append(limit)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM notes WHERE {' AND '.join(where)} "
            f"ORDER BY pinned DESC, updated_at DESC LIMIT ?", args).fetchall()
    return rows_to_dicts(rows)


# ------------------------------------------------------------------- Suche

def search(query: str, limit: int = 20, semantic: bool = True) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return recent(limit)
    hits: dict[int, dict[str, Any]] = {}

    for row in _fts(query, limit):
        row["match"] = "wort"
        hits[row["id"]] = row

    if semantic and _embeddings_on():
        for row, score in _semantic(query, limit):
            existing = hits.get(row["id"])
            if existing:
                existing["match"] = "beides"
                existing["score"] = score
            else:
                row["match"] = "sinn"
                row["score"] = score
                hits[row["id"]] = row

    order = {"beides": 0, "wort": 1, "sinn": 2}
    return sorted(hits.values(),
                  key=lambda r: (order.get(r.get("match"), 3),
                                 -(r.get("score") or 0)))[:limit]


def _fts(query: str, limit: int) -> list[dict[str, Any]]:
    # FTS5 stolpert über Sonderzeichen — deshalb jedes Wort als Präfix quoten.
    terms = " ".join(f'"{w}"*' for w in query.split() if w.strip())
    if not terms:
        return []
    try:
        with get_db() as db:
            rows = db.execute(
                """SELECT n.* FROM notes_fts f JOIN notes n ON n.id = f.rowid
                   WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?""",
                (terms, limit)).fetchall()
        return rows_to_dicts(rows)
    except Exception as e:                     # kaputte Suchsyntax soll nichts kippen
        log.info("Volltextsuche fehlgeschlagen: %s", e)
        return []


def _semantic(query: str, limit: int) -> list[tuple[dict[str, Any], float]]:
    try:
        vector = embed([query])[0]
    except OllamaUnavailable as e:
        log.info("Semantische Suche nicht möglich: %s", e)
        return []
    with get_db() as db:
        rows = db.execute(
            """SELECT n.*, v.vec FROM note_vectors v JOIN notes n ON n.id = v.note_id
            """).fetchall()
    scored: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        stored = unpack_vector(row["vec"])
        if len(stored) != len(vector):
            continue
        score = sum(a * b for a, b in zip(stored, vector))
        if score > 0.45:                       # darunter ist es Zufall, kein Treffer
            item = dict(row)
            item.pop("vec", None)
            scored.append((item, round(score, 3)))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:limit]


def _embed_one(note_id: int, title: str, body: str) -> None:
    if not _embeddings_on():
        return
    try:
        vector = embed([f"{title}\n{body}"[:4000]])[0]
    except OllamaUnavailable as e:
        log.info("Notiz %s ohne Vektor gespeichert (%s) — wird nachgeholt.", note_id, e)
        return
    with get_db() as db:
        db.execute(
            """INSERT INTO note_vectors(note_id, model, dim, vec, updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(note_id) DO UPDATE SET model=excluded.model,
                 dim=excluded.dim, vec=excluded.vec, updated_at=excluded.updated_at""",
            (note_id, embed_model(), len(vector), pack_vector(vector), now_str()))


def backfill(limit: int = 20) -> int:
    """Notizen ohne Vektor nachtragen — läuft stündlich im Hintergrund."""
    if not _embeddings_on():
        return 0
    with get_db() as db:
        rows = db.execute(
            """SELECT n.id, n.title, n.body FROM notes n
               LEFT JOIN note_vectors v ON v.note_id = n.id
               WHERE v.note_id IS NULL LIMIT ?""", (limit,)).fetchall()
    done = 0
    for row in rows:
        _embed_one(row["id"], row["title"] or "", row["body"])
        done += 1
    return done


def stats() -> dict[str, Any]:
    with get_db() as db:
        row = db.execute(
            """SELECT (SELECT COUNT(*) FROM notes) AS gesamt,
                      (SELECT COUNT(*) FROM note_vectors) AS mit_vektor""").fetchone()
    out = dict(row)
    out["semantisch"] = _embeddings_on()
    return out
