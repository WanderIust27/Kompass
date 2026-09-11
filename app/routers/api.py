"""Die HTTP-Schnittstelle.

Bewusst flach: ein Router, sprechende Pfade, Wortlaute auf Deutsch, wo sie
in der Oberfläche auftauchen. Fehler werden nicht hier abgefangen, sondern
zentral in main.py übersetzt — KeyError wird 404, ValueError wird 400,
PermissionError wird 409 (das ist der Fall „Limit erreicht“).
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from ..config import ALLOW_WEB, TOKEN
from ..db import all_settings, recent_events, set_setting
from ..version import BUILT_AT, VERSION
from ..services import (briefing, chat, notes, ollama_client, people, planner,
                        profile, projects, purchases, recommendations, routines,
                        scheduler, tasks, triage, websearch)


def auth(request: Request) -> None:
    """Schutz nur, wenn KOMPASS_TOKEN gesetzt ist — sonst offen im Heimnetz."""
    if not TOKEN:
        return
    given = (request.headers.get("x-token")
             or request.query_params.get("token") or "")
    if given != TOKEN:
        raise HTTPException(status_code=401, detail="Token fehlt oder stimmt nicht.")


router = APIRouter(prefix="/api", dependencies=[Depends(auth)])


# ------------------------------------------------------------------ Zustand

@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "version": VERSION,
        "built_at": BUILT_AT,
        "ollama": {
            "erreichbar": ollama_client.is_available(),
            "modell": ollama_client.active_model(),
            "vorhanden": ollama_client.model_present(),
            "einbettung": ollama_client.embed_model(),
        },
        "web": ALLOW_WEB,
        "inbox": triage.pending_count(),
        "aufgaben": tasks.counts(),
        "haushalt": routines.stats(),
        "projekte": projects.slots(),
        "notizen": notes.stats(),
    }


@router.get("/settings")
def read_settings() -> dict[str, str]:
    return all_settings()


@router.post("/settings")
def write_settings(data: dict[str, Any] = Body(...)) -> dict[str, str]:
    for key, value in data.items():
        set_setting(key, "" if value is None else str(value))
    if {"morning_hour", "evening_hour"} & set(data):
        scheduler.refresh()
    return all_settings()


@router.get("/events")
def events(limit: int = 25) -> list[dict[str, Any]]:
    return recent_events(limit)


@router.get("/models")
def models() -> dict[str, Any]:
    return {"presets": ollama_client.MODEL_PRESETS,
            "installiert": ollama_client.installed_models(),
            "aktiv": ollama_client.active_model(),
            "pull": ollama_client.pull_state()}


@router.post("/models")
def choose_model(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Kein Modell angegeben.")
    set_setting("ollama_model", name)
    if not ollama_client.model_present(name):
        threading.Thread(target=ollama_client.pull_model, args=(name,),
                         daemon=True).start()
    return {"aktiv": name, "pull": ollama_client.pull_state()}


# -------------------------------------------------------------------- Inbox

@router.get("/inbox")
def inbox(status: str = "new", limit: int = 100) -> list[dict[str, Any]]:
    return triage.query(status, limit)


@router.post("/inbox")
def inbox_add(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return triage.add(data.get("raw") or data.get("text") or "")


@router.post("/inbox/sort")
def inbox_sort(limit: int = 10) -> dict[str, Any]:
    return {"eingeschätzt": triage.sort_all(limit), "inbox": triage.query("new")}


@router.post("/inbox/{inbox_id}/suggest")
def inbox_suggest(inbox_id: int) -> dict[str, Any]:
    return triage.suggest(inbox_id)


@router.post("/inbox/{inbox_id}/apply")
def inbox_apply(inbox_id: int, data: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return triage.apply(inbox_id, data.get("kind"), data.get("fields"))


@router.post("/inbox/{inbox_id}/dismiss")
def inbox_dismiss(inbox_id: int) -> dict[str, Any]:
    return triage.dismiss(inbox_id)


@router.delete("/inbox/{inbox_id}")
def inbox_delete(inbox_id: int) -> dict[str, str]:
    triage.delete(inbox_id)
    return {"ok": "gelöscht"}


# -------------------------------------------------------------------- Heute

@router.get("/today")
def today(day: str | None = None) -> dict[str, Any]:
    return planner.today(day)


@router.post("/today/plan")
def today_plan(day: str | None = None) -> dict[str, Any]:
    return planner.plan(day)


@router.get("/briefing")
def get_briefing(slot: str = "morning", force: bool = False,
                 day: str | None = None) -> dict[str, Any]:
    if slot == "evening":
        return briefing.evening(day, force)
    return briefing.morning(day, force)


@router.get("/briefing/history")
def briefing_history(limit: int = 10) -> list[dict[str, Any]]:
    return briefing.recent(limit)


@router.post("/checkin")
def checkin(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return briefing.save_checkin(data)


@router.get("/checkins")
def checkin_list(limit: int = 30) -> list[dict[str, Any]]:
    return briefing.checkins(limit)


# ----------------------------------------------------------------- Aufgaben

@router.get("/tasks")
def task_list(status: str = "open", area: str | None = None,
              project_id: int | None = None, day: str | None = None,
              energy: str | None = None, context: str | None = None,
              unplanned: bool = False, limit: int = 300) -> list[dict[str, Any]]:
    return tasks.query(status, area, project_id, day, energy, context, unplanned, limit)


@router.post("/tasks")
def task_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return tasks.create(data)


@router.patch("/tasks/{task_id}")
def task_update(task_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return tasks.update(task_id, data)


@router.post("/tasks/{task_id}/done")
def task_done(task_id: int, done: bool = True) -> dict[str, Any]:
    return tasks.complete(task_id, done)


@router.post("/tasks/{task_id}/snooze")
def task_snooze(task_id: int, days: int = 1) -> dict[str, Any]:
    return tasks.snooze(task_id, days)


@router.post("/tasks/{task_id}/unplan")
def task_unplan(task_id: int) -> dict[str, Any]:
    return planner.unplan(task_id)


@router.delete("/tasks/{task_id}")
def task_delete(task_id: int) -> dict[str, str]:
    tasks.delete(task_id)
    return {"ok": "gelöscht"}


# ----------------------------------------------------------------- Haushalt

@router.get("/routines")
def routine_list(active_only: bool = True, room: str | None = None) -> list[dict[str, Any]]:
    return routines.query(active_only, room)


@router.get("/routines/due")
def routine_due(day: str | None = None) -> list[dict[str, Any]]:
    return routines.due(day)


@router.get("/routines/stats")
def routine_stats() -> dict[str, Any]:
    return {"zahlen": routines.stats(), "räume": routines.rooms()}


@router.post("/routines")
def routine_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return routines.create(data)


@router.patch("/routines/{routine_id}")
def routine_update(routine_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return routines.update(routine_id, data)


@router.post("/routines/{routine_id}/done")
def routine_done(routine_id: int, data: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return routines.complete(routine_id, (data or {}).get("note"))


@router.post("/routines/{routine_id}/snooze")
def routine_snooze(routine_id: int, days: int = 1) -> dict[str, Any]:
    return routines.snooze(routine_id, days)


@router.delete("/routines/{routine_id}")
def routine_delete(routine_id: int) -> dict[str, str]:
    routines.delete(routine_id)
    return {"ok": "gelöscht"}


# ------------------------------------------------------- Ideen und Projekte

@router.get("/ideas")
def idea_list(status: str | None = None) -> list[dict[str, Any]]:
    return projects.ideas(status)


@router.post("/ideas")
def idea_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return projects.add_idea(data.get("title") or data.get("titel") or "",
                             data.get("note"), data.get("cooldown"))


@router.patch("/ideas/{idea_id}")
def idea_update(idea_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return projects.update_idea(idea_id, data)


@router.get("/ideas/questions")
def idea_questions() -> list[dict[str, str]]:
    return [{"key": k, "frage": q} for k, q in projects.RITUAL_QUESTIONS]


@router.post("/ideas/{idea_id}/review")
def idea_review(idea_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return projects.review(idea_id, data.get("answers") or data)


@router.post("/ideas/{idea_id}/promote")
def idea_promote(idea_id: int, data: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    data = data or {}
    return projects.promote(idea_id, data.get("override_reason"),
                            data.get("deadline"), data.get("next_action"))


@router.post("/ideas/{idea_id}/drop")
def idea_drop(idea_id: int) -> dict[str, Any]:
    return projects.drop_idea(idea_id)


@router.post("/ideas/{idea_id}/sleep")
def idea_sleep(idea_id: int, days: int = 30) -> dict[str, Any]:
    return projects.sleep_idea(idea_id, days)


@router.delete("/ideas/{idea_id}")
def idea_delete(idea_id: int) -> dict[str, str]:
    projects.delete_idea(idea_id)
    return {"ok": "gelöscht"}


@router.get("/projects")
def project_list(status: str | None = "active") -> list[dict[str, Any]]:
    return projects.projects(status)


@router.get("/projects/slots")
def project_slots() -> dict[str, Any]:
    return {"slots": projects.slots(), "liegengeblieben": projects.stale()}


@router.post("/projects")
def project_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return projects.add_project(data.get("title") or "", data.get("why"),
                                data.get("deadline"), data.get("next_action"),
                                None, data.get("override_reason"))


@router.patch("/projects/{project_id}")
def project_update(project_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return projects.update_project(project_id, data)


@router.delete("/projects/{project_id}")
def project_delete(project_id: int) -> dict[str, str]:
    projects.delete_project(project_id)
    return {"ok": "gelöscht"}


# -------------------------------------------------------------------- Käufe

@router.get("/purchases")
def purchase_list(status: str | None = None) -> list[dict[str, Any]]:
    return purchases.query(status)


@router.get("/purchases/meta")
def purchase_meta() -> dict[str, Any]:
    return {"fragen": [{"key": k, "frage": q} for k, q in purchases.QUESTIONS],
            "budget": purchases.budget_state(),
            "zahlen": purchases.stats(),
            "nutzung_offen": purchases.usage_due(),
            "web": websearch.enabled()}


@router.post("/purchases")
def purchase_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return purchases.create(data)


@router.post("/purchases/{purchase_id}/answer")
def purchase_answer(purchase_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return purchases.answer(purchase_id, data.get("answers") or data)


@router.post("/purchases/{purchase_id}/research")
def purchase_research(purchase_id: int) -> dict[str, Any]:
    return purchases.research(purchase_id)


@router.post("/purchases/{purchase_id}/decide")
def purchase_decide(purchase_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return purchases.decide(purchase_id, data.get("verdict") or "verworfen",
                            data.get("price"))


@router.post("/purchases/{purchase_id}/usage")
def purchase_usage(purchase_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return purchases.set_usage(purchase_id, data.get("verdict") or "manchmal")


@router.delete("/purchases/{purchase_id}")
def purchase_delete(purchase_id: int) -> dict[str, str]:
    purchases.delete(purchase_id)
    return {"ok": "gelöscht"}


# ------------------------------------------------------------------ Notizen

@router.get("/notes")
def note_list(q: str | None = None, limit: int = 50,
              project_id: int | None = None) -> list[dict[str, Any]]:
    if q:
        return notes.search(q, limit)
    return notes.recent(limit, project_id)


@router.post("/notes")
def note_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return notes.create(data)


@router.patch("/notes/{note_id}")
def note_update(note_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return notes.update(note_id, data)


@router.delete("/notes/{note_id}")
def note_delete(note_id: int) -> dict[str, str]:
    notes.delete(note_id)
    return {"ok": "gelöscht"}


# ----------------------------------------------------------------- Menschen

@router.get("/people")
def people_list(active_only: bool = True) -> list[dict[str, Any]]:
    return people.query(active_only)


@router.get("/people/due")
def people_due() -> dict[str, Any]:
    return {"fällig": people.due(), "geburtstage": people.birthdays(60)}


@router.post("/people")
def people_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return people.create(data)


@router.patch("/people/{person_id}")
def people_update(person_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return people.update(person_id, data)


@router.post("/people/{person_id}/contact")
def people_contact(person_id: int, data: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return people.log_contact(person_id, (data or {}).get("what"))


@router.get("/people/{person_id}/history")
def people_history(person_id: int, limit: int = 20) -> list[dict[str, Any]]:
    return people.history(person_id, limit)


@router.delete("/people/{person_id}")
def people_delete(person_id: int) -> dict[str, str]:
    people.delete(person_id)
    return {"ok": "gelöscht"}


# -------------------------------------------------------------- Empfehlungen

@router.get("/recs")
def rec_list(kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    return recommendations.query(kind, status)


@router.get("/recs/meta")
def rec_meta() -> dict[str, Any]:
    return {"sorten": recommendations.KINDS, "zahlen": recommendations.stats(),
            "web": websearch.enabled()}


@router.post("/recs")
def rec_create(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return recommendations.create(data)


@router.post("/recs/suggest")
def rec_suggest(data: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    data = data or {}
    return {"vorschläge": recommendations.suggest(
        data.get("kind") or "book", int(data.get("count") or 4), data.get("hint"))}


@router.get("/recs/lookup")
def rec_lookup(title: str = Query(...), kind: str = "book") -> list[dict[str, Any]]:
    return recommendations.lookup(title, kind)


@router.patch("/recs/{rec_id}")
def rec_update(rec_id: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return recommendations.update(rec_id, data)


@router.delete("/recs/{rec_id}")
def rec_delete(rec_id: int) -> dict[str, str]:
    recommendations.delete(rec_id)
    return {"ok": "gelöscht"}


# --------------------------------------------------------------------- Chat

@router.get("/chat")
def chat_history(limit: int = 40) -> list[dict[str, Any]]:
    return chat.history(limit)


@router.post("/chat")
def chat_send(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return chat.send(data.get("message") or "")


@router.delete("/chat")
def chat_clear() -> dict[str, str]:
    chat.clear()
    return {"ok": "geleert"}


# ------------------------------------------------------------------- Muster

@router.get("/profile")
def profile_read() -> list[dict[str, Any]]:
    return profile.facts()


@router.post("/profile")
def profile_recompute() -> list[dict[str, Any]]:
    return profile.recompute()
