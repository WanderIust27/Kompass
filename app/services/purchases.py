"""Kaufberatung — Wartefrist, Verhör, Recherche, Budget, spätere Ehrlichkeit.

Die Reihenfolge ist Absicht. Erst wartet der Kauf, dann wird gefragt, dann
erst darf recherchiert werden — wer mit der Recherche anfängt, hat sich in
der Regel schon entschieden und sucht nur noch Bestätigung.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from ..db import (get_db, get_float, get_int, get_setting, log_event,
                  rows_to_dicts, today_str)
from . import websearch
from .ollama_client import OllamaUnavailable, generate, generate_json

log = logging.getLogger("kompass.kauf")

QUESTIONS = [
    ("problem", "Welches Problem löst es — heute, nicht theoretisch?"),
    ("current", "Was benutzt du dafuer gerade, und warum reicht das nicht?"),
    ("without", "Was passiert, wenn du es nicht kaufst?"),
    ("future", "Wo steht das Ding in drei Monaten?"),
]


def wait_hours_for(price: float | None) -> int:
    """Wartefrist nach Preis. Schwellen stehen in den Einstellungen."""
    if price is None:
        return get_int("buy_wait_small_h", 48)
    small = get_float("buy_threshold_small", 20)
    big = get_float("buy_threshold_big", 100)
    if price >= big:
        return get_int("buy_wait_big_h", 168)
    if price >= small:
        return get_int("buy_wait_small_h", 48)
    return 0


def create(data: dict[str, Any]) -> dict[str, Any]:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Ein Wunsch braucht einen Namen.")
    price = _as_price(data.get("price_eur"))
    hours = wait_hours_for(price)
    until = (datetime.now() + timedelta(hours=hours)).replace(microsecond=0)
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO purchases(title, price_eur, url, category, reason,
                                     status, wait_until, wait_hours)
               VALUES(?,?,?,?,?,?,?,?)""",
            (title, price, data.get("url"), data.get("category"),
             data.get("reason"), "waiting" if hours else "ready",
             until.isoformat(sep=" "), hours))
        new_id = cur.lastrowid
    return get(new_id)


def _as_price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(str(value).replace(",", ".")), 2)
    except ValueError:
        return None


def get(purchase_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,)).fetchone()
    if not row:
        raise KeyError(f"Kauf {purchase_id} gibt es nicht.")
    return _decorate(dict(row))


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("answers_json", "research_json"):
        if row.get(key):
            try:
                row[key[:-5]] = json.loads(row[key])
            except ValueError:
                row[key[:-5]] = None
    until = row.get("wait_until")
    row["hours_left"] = 0
    if until and row.get("status") == "waiting":
        try:
            left = datetime.fromisoformat(until) - datetime.now()
            row["hours_left"] = max(0, round(left.total_seconds() / 3600, 1))
        except ValueError:
            pass
    return row


def query(status: str | None = None) -> list[dict[str, Any]]:
    where, args = ["1=1"], []
    if status and status != "alle":
        where.append("status=?")
        args.append(status)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM purchases WHERE {' AND '.join(where)} "
            f"ORDER BY CASE status WHEN 'ready' THEN 0 WHEN 'waiting' THEN 1 "
            f"ELSE 2 END, wait_until, id DESC", args).fetchall()
    return [_decorate(dict(r)) for r in rows]


def ripen() -> int:
    """Abgelaufene Wartefristen freigeben. Läuft im Hintergrund."""
    now = datetime.now().isoformat(sep=" ")
    with get_db() as db:
        cur = db.execute(
            "UPDATE purchases SET status='ready' WHERE status='waiting' AND wait_until<=?",
            (now,))
        count = cur.rowcount or 0
    if count:
        log_event("käufe", f"{count} Wunsch/Wünsche haben die Wartefrist hinter sich.")
    return count


def answer(purchase_id: int, answers: dict[str, str]) -> dict[str, Any]:
    """Antworten aus dem Verhör festhalten und das Modell draufschauen lassen."""
    item = get(purchase_id)
    with get_db() as db:
        db.execute("UPDATE purchases SET answers_json=? WHERE id=?",
                   (json.dumps(answers, ensure_ascii=False), purchase_id))
    take = _ai_take(item, answers)
    if take:
        with get_db() as db:
            db.execute("UPDATE purchases SET ai_take=? WHERE id=?", (take, purchase_id))
    return get(purchase_id)


def _ai_take(item: dict[str, Any], answers: dict[str, str]) -> str | None:
    lines = [f"{label} — {answers.get(key, '(keine Antwort)')}"
             for key, label in QUESTIONS]
    budget = budget_state()
    prompt = (
        f"Wunsch: {item['title']}\n"
        f"Preis: {item.get('price_eur') or 'unbekannt'} Euro\n"
        f"Begründung beim Eintragen: {item.get('reason') or '—'}\n\n"
        + "\n".join(lines)
        + (f"\n\nBudget diesen Monat: {budget['spent']:.0f} von "
           f"{budget['budget']:.0f} Euro schon ausgegeben."
           if budget.get("budget") else "")
        + "\n\nSchreib drei bis fuenf Sätze: Wo die Antworten tragen und wo sie "
          "dünn sind, und was du an seiner Stelle tätest. Keine Ueberschriften, "
          "keine Aufzählung, kein Vorwort.")
    try:
        return generate(prompt, system=_SYSTEM, temperature=0.5)
    except OllamaUnavailable as e:
        log.info("Keine Einschätzung möglich: %s", e)
        return None


_SYSTEM = (
    "Du bist Kompass, der Alltagsassistent eines Menschen mit ADHS. "
    "Beim Thema Kaufen bist du der ruhige Freund, der nicht moralisiert, aber "
    "auch nicht mitschwärmt. Du duzt. Du sagst klar, was du denkst, und "
    "erfindest keine Preise oder Testergebnisse. Deutsch, knapp, ohne Floskeln.")


def research(purchase_id: int) -> dict[str, Any]:
    """Im Netz nachsehen: Preis, Kritik, günstigere Alternative."""
    item = get(purchase_id)
    if not websearch.enabled():
        raise websearch.WebDisabled(
            "Internetzugriff ist abgeschaltet — setz ALLOW_WEB=1 in der .env.")
    title = item["title"]
    found: dict[str, Any] = {"gesucht_am": today_str(), "treffer": {}}
    for label, query in (("preis", websearch.price_query(title)),
                         ("kritik", websearch.review_query(title)),
                         ("alternativen", websearch.alternative_query(title))):
        try:
            found["treffer"][label] = websearch.search(query, limit=5)
        except Exception as e:                       # Netz ist unzuverlässig
            log.info("Suche '%s' fehlgeschlagen: %s", query, e)
            found["treffer"][label] = []

    digest = []
    for label, hits in found["treffer"].items():
        for h in hits[:4]:
            digest.append(f"[{label}] {h['title']} — {h['snippet'][:200]} ({h['url']})")
    summary = None
    if digest:
        prompt = (f"Wunsch: {title} (etwa {item.get('price_eur') or '?'} Euro)\n\n"
                  "Suchergebnisse:\n" + "\n".join(digest[:14]) +
                  "\n\nFass zusammen, was davon wirklich brauchbar ist: übliche "
                  "Preisspanne, die häufigste Kritik, und ob es eine günstigere "
                  "oder gebrauchte Alternative gibt. Wenn die Ergebnisse nichts "
                  "hergeben, sag genau das. Höchstens sechs Sätze.")
        try:
            summary = generate(prompt, system=_SYSTEM, temperature=0.4)
        except OllamaUnavailable as e:
            log.info("Zusammenfassung nicht möglich: %s", e)
    found["zusammenfassung"] = summary
    with get_db() as db:
        db.execute("UPDATE purchases SET research_json=? WHERE id=?",
                   (json.dumps(found, ensure_ascii=False), purchase_id))
    return get(purchase_id)


def decide(purchase_id: int, verdict: str, price: float | None = None) -> dict[str, Any]:
    """gekauft | verworfen — beides zählt fuer deine Trefferquote."""
    item = get(purchase_id)
    now = today_str()
    if verdict == "gekauft":
        check_days = get_int("buy_usage_check_days", 30)
        check_at = (datetime.now() + timedelta(days=check_days)).date().isoformat()
        with get_db() as db:
            db.execute(
                """UPDATE purchases SET status='bought', bought_at=?, decided_at=?,
                       bought_price=?, usage_check_at=? WHERE id=?""",
                (now, now, _as_price(price) if price is not None
                 else item.get("price_eur"), check_at, purchase_id))
        log_event("käufe", f"Gekauft: {item['title']}.")
    else:
        with get_db() as db:
            db.execute("UPDATE purchases SET status='dropped', decided_at=? WHERE id=?",
                       (now, purchase_id))
        log_event("käufe",
                  f"Verworfen: {item['title']}"
                  + (f" — {item['price_eur']:.0f} Euro nicht ausgegeben."
                     if item.get("price_eur") else "."))
    return get(purchase_id)


def delete(purchase_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM purchases WHERE id=?", (purchase_id,))


def usage_due() -> list[dict[str, Any]]:
    """Gekauftes, bei dem die Nachfrage ansteht: benutzt du es überhaupt?"""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM purchases WHERE status='bought' AND usage_verdict IS NULL "
            "AND usage_check_at<=? ORDER BY usage_check_at", (today_str(),)).fetchall()
    return [_decorate(dict(r)) for r in rows]


def set_usage(purchase_id: int, verdict: str) -> dict[str, Any]:
    with get_db() as db:
        db.execute("UPDATE purchases SET usage_verdict=? WHERE id=?",
                   (verdict, purchase_id))
    return get(purchase_id)


def budget_state(month: str | None = None) -> dict[str, Any]:
    month = month or today_str()[:7]
    budget = get_setting("buy_budget_month", "") or ""
    with get_db() as db:
        row = db.execute(
            """SELECT COALESCE(SUM(COALESCE(bought_price, price_eur)), 0) AS spent,
                      COUNT(*) AS n
               FROM purchases WHERE status='bought' AND substr(bought_at,1,7)=?""",
            (month,)).fetchone()
    spent = float(row["spent"] or 0)
    try:
        total = float(budget)
    except ValueError:
        total = 0.0
    return {"month": month, "spent": spent, "count": int(row["n"]),
            "budget": total, "left": round(total - spent, 2) if total else None}


def stats() -> dict[str, Any]:
    """Deine Trefferquote — das Argument, das beim nächsten Mal wirkt."""
    with get_db() as db:
        row = db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM purchases WHERE status='waiting') AS wartet,
                 (SELECT COUNT(*) FROM purchases WHERE status='ready') AS entscheiden,
                 (SELECT COUNT(*) FROM purchases WHERE status='bought') AS gekauft,
                 (SELECT COUNT(*) FROM purchases WHERE status='dropped') AS verworfen,
                 (SELECT COALESCE(SUM(price_eur),0) FROM purchases
                    WHERE status='dropped') AS gespart,
                 (SELECT COUNT(*) FROM purchases WHERE usage_verdict='nie') AS nie_benutzt,
                 (SELECT COUNT(*) FROM purchases WHERE usage_verdict='oft') AS oft_benutzt
            """).fetchone()
    out = dict(row)
    out["gespart"] = round(float(out["gespart"] or 0), 2)
    entschieden = int(out["gekauft"]) + int(out["verworfen"])
    out["verwerfungsquote"] = (round(int(out["verworfen"]) / entschieden * 100)
                               if entschieden else None)
    return out
