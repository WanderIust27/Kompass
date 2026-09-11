"""Hintergrundarbeit.

Kompass schickt keine Push-Nachrichten — so war es gewünscht. Trotzdem muss
im Hintergrund etwas laufen, damit morgens ein Briefing dasteht, Karenzzeiten
ablaufen und der Tagesplan nicht von gestern ist.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import TZ
from ..db import get_int, log_event
from . import briefing, notes, planner, profile, projects, purchases, tasks

log = logging.getLogger("kompass.scheduler")

_scheduler: BackgroundScheduler | None = None


def start() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(timezone=TZ)
    _register()
    _scheduler.start()
    log.info("Hintergrundarbeit läuft.")


def refresh() -> None:
    """Nach einer Aenderung der Uhrzeiten neu einhängen."""
    if not _scheduler:
        return
    for job in _scheduler.get_jobs():
        job.remove()
    _register()
    log.info("Zeiten neu gesetzt.")


def _register() -> None:
    assert _scheduler is not None
    morning = get_int("morning_hour", 7)
    evening = get_int("evening_hour", 21)
    _scheduler.add_job(nightly, "cron", hour=3, minute=10, id="nightly")
    _scheduler.add_job(morning_job, "cron", hour=morning, minute=0, id="morning")
    _scheduler.add_job(evening_job, "cron", hour=evening, minute=0, id="evening")
    _scheduler.add_job(hourly, "interval", hours=1, id="hourly")


def nightly() -> None:
    """Aufräumen, bevor der Tag anfängt."""
    try:
        tasks.roll_over()
        projects.ripen()
        purchases.ripen()
        profile.recompute()
    except Exception as e:
        log.warning("Nächtliche Arbeit unvollständig: %s", e)


def morning_job() -> None:
    try:
        planner.plan()
        briefing.morning(force=True)
        log_event("briefing", "Morgenbriefing steht.")
    except Exception as e:
        log.warning("Morgenbriefing fehlgeschlagen: %s", e)


def evening_job() -> None:
    try:
        briefing.evening(force=True)
        log_event("briefing", "Abend-Check-in steht.")
    except Exception as e:
        log.warning("Abend-Check-in fehlgeschlagen: %s", e)


def hourly() -> None:
    try:
        done = notes.backfill(20)
        if done:
            log.info("%d Notiz(en) nachträglich eingebettet.", done)
    except Exception as e:
        log.info("Einbettungen nicht nachgetragen: %s", e)


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
