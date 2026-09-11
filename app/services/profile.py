"""Was Kompass über dich gelernt hat.

Alles hier ist gerechnet, nicht geraten — aus deinen eigenen Zahlen. Das ist
Absicht: Ein Satz wie „du unterschätzt Zeit“ wirkt nur, wenn eine Zahl
dahintersteht, die du nachrechnen kannst.
"""
from __future__ import annotations

import json
from typing import Any

from ..db import get_db, rows_to_dicts, weekday_key, parse_day


def recompute() -> list[dict[str, Any]]:
    facts: list[tuple[str, str, Any]] = []

    with get_db() as db:
        done14 = db.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE status='done' "
            "AND done_at>=date('now','localtime','-14 day')").fetchone()["n"]
        created14 = db.execute(
            "SELECT COUNT(*) AS n FROM tasks "
            "WHERE created_at>=date('now','localtime','-14 day')").fetchone()["n"]
        snooze = db.execute(
            "SELECT AVG(snoozes) AS s FROM tasks WHERE status='done' "
            "AND done_at>=date('now','localtime','-30 day')").fetchone()["s"]
        weekdays = db.execute(
            "SELECT done_at FROM tasks WHERE status='done' "
            "AND done_at>=date('now','localtime','-60 day')").fetchall()
        routine_rows = db.execute(
            "SELECT COUNT(*) AS n FROM routine_log "
            "WHERE day>=date('now','localtime','-30 day')").fetchone()["n"]
        routine_count = db.execute(
            "SELECT COUNT(*) AS n FROM routines WHERE active=1").fetchone()["n"]
        buys = db.execute(
            """SELECT
                 SUM(CASE WHEN status='bought' THEN 1 ELSE 0 END) AS gekauft,
                 SUM(CASE WHEN status='dropped' THEN 1 ELSE 0 END) AS verworfen,
                 SUM(CASE WHEN usage_verdict='nie' THEN 1 ELSE 0 END) AS nie,
                 SUM(CASE WHEN usage_verdict IS NOT NULL THEN 1 ELSE 0 END) AS geprüft
               FROM purchases""").fetchone()
        ideas = db.execute(
            """SELECT
                 SUM(CASE WHEN status='promoted' THEN 1 ELSE 0 END) AS projekt,
                 SUM(CASE WHEN status='dropped' THEN 1 ELSE 0 END) AS verworfen,
                 COUNT(*) AS gesamt FROM ideas""").fetchone()

    if created14:
        quote = round(done14 / created14 * 100)
        facts.append(("erledigungsquote",
                      f"In den letzten zwei Wochen sind {done14} von {created14} neuen "
                      f"Aufgaben fertig geworden ({quote} Prozent).",
                      {"done": done14, "created": created14, "pct": quote}))

    if snooze is not None and snooze >= 0.8:
        facts.append(("verschieben",
                      f"Eine erledigte Aufgabe wird im Schnitt {snooze:.1f} mal "
                      f"verschoben, bevor sie drankommt. Plan kleiner.",
                      {"avg": round(float(snooze), 2)}))

    if weekdays:
        counter: dict[str, int] = {}
        for row in weekdays:
            day = parse_day(row["done_at"])
            if day:
                key = weekday_key(day)
                counter[key] = counter.get(key, 0) + 1
        if counter:
            best = max(counter, key=lambda k: counter[k])
            worst = min(counter, key=lambda k: counter[k])
            if counter[best] >= 3 and best != worst:
                facts.append(("wochentag",
                              f"Am meisten schaffst du dienstags bis sonntags "
                              f"gesehen am {best}, am wenigsten am {worst}.",
                              counter))

    if routine_count:
        erwartet = max(1, routine_count * 2)
        treue = round(routine_rows / erwartet * 100)
        facts.append(("haushalt",
                      f"Im letzten Monat hast du {routine_rows} Haushaltsroutinen "
                      f"abgehakt.", {"log": routine_rows, "quote": treue}))

    entschieden = int(buys["gekauft"] or 0) + int(buys["verworfen"] or 0)
    if entschieden >= 3:
        quote = round(int(buys["verworfen"] or 0) / entschieden * 100)
        facts.append(("kaufdisziplin",
                      f"Von {entschieden} Wünschen mit abgelaufener Wartefrist hast "
                      f"du {quote} Prozent wieder verworfen.",
                      {"verworfen_pct": quote}))
    if int(buys["geprüft"] or 0) >= 3:
        nie = int(buys["nie"] or 0)
        facts.append(("kaufnutzen",
                      f"Von {buys['geprüft']} nachgeprüften Käufen liegen {nie} "
                      f"ungenutzt herum.", {"nie": nie}))

    if int(ideas["gesamt"] or 0) >= 5:
        projekt = int(ideas["projekt"] or 0)
        quote = round(projekt / int(ideas["gesamt"]) * 100)
        facts.append(("ideen",
                      f"Von {ideas['gesamt']} Ideen sind {projekt} wirklich Projekt "
                      f"geworden ({quote} Prozent). Der Rest war Impuls.",
                      {"pct": quote}))

    with get_db() as db:
        for key, text, value in facts:
            db.execute(
                """INSERT INTO profile_facts(key, text, value_json, updated_at)
                   VALUES(?,?,?,datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET text=excluded.text,
                     value_json=excluded.value_json, updated_at=excluded.updated_at""",
                (key, text, json.dumps(value, ensure_ascii=False)))
    return facts_list()


def facts_list() -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM profile_facts ORDER BY key").fetchall()
    return rows_to_dicts(rows)


def facts() -> list[dict[str, Any]]:
    return facts_list()
