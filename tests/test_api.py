"""Smoke-Test der API: sprechen alle Endpunkte, und stimmen die Daten?

Startet die echte Anwendung gegen eine Wegwerf-Datenbank. Ollama zeigt ins
Leere und Internet ist aus — Kompass muss auch dann vollstaendig bedienbar
bleiben, sonst taugt er im Alltag nichts.

Aufruf:  python3 tests/test_api.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["KOMPASS_DATA_DIR"] = tempfile.mkdtemp(prefix="kompass-api-")
os.environ["OLLAMA_URL"] = "http://127.0.0.1:1"
os.environ["ALLOW_WEB"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient        # noqa: E402
from app.main import app                         # noqa: E402

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


def ok(name, response, expected=200):
    check(name, response.status_code, expected)
    return response


with TestClient(app) as c:
    print("\n— Zustand —")
    status = ok("Status", c.get("/api/status")).json()
    check("Version steht drin", bool(status["version"]), True)
    check("ohne Ollama meldet er das ehrlich", status["ollama"]["erreichbar"], False)
    ok("Gesundheitsprobe", c.get("/health"))
    ok("Oberfläche", c.get("/"))
    ok("Manifest", c.get("/manifest.json"))
    ok("Service Worker", c.get("/sw.js"))

    print("\n— Inbox —")
    item = ok("Reinwerfen", c.post("/api/inbox", json={"raw": "Fenster putzen"})).json()
    ok("Einschaetzen", c.post(f"/api/inbox/{item['id']}/suggest"))
    ok("Uebernehmen", c.post(f"/api/inbox/{item['id']}/apply", json={}))
    check("leeres Reinwerfen wird abgelehnt",
          c.post("/api/inbox", json={"raw": "  "}).status_code, 400)

    print("\n— Aufgaben —")
    task = ok("Anlegen", c.post("/api/tasks", json={"title": "Test", "est_min": 5})).json()
    ok("Liste", c.get("/api/tasks"))
    ok("Aendern", c.patch(f"/api/tasks/{task['id']}", json={"priority": 1}))
    ok("Schieben", c.post(f"/api/tasks/{task['id']}/snooze?days=2"))
    ok("Abhaken", c.post(f"/api/tasks/{task['id']}/done"))
    check("erfundene ID gibt sauber 404",
          c.post("/api/tasks/9999/done").status_code, 404)
    check("Aufgabe ohne Titel wird abgelehnt",
          c.post("/api/tasks", json={"title": ""}).status_code, 400)

    print("\n— Tag und Briefing —")
    ok("Heute", c.get("/api/today"))
    plan = ok("Planen", c.post("/api/today/plan")).json()
    check("Plan kennt seine Kapazitaet", plan["capacity_min"] > 0, True)
    brief = ok("Briefing ohne Modell", c.get("/api/briefing")).json()
    check("es kommt trotzdem Text", len(brief["text"]) > 20, True)
    ok("Abendfassung", c.get("/api/briefing?slot=evening"))
    ok("Check-in", c.post("/api/checkin", json={"mood": 4, "energy": 3, "note": "ging"}))

    print("\n— Haushalt —")
    ok("Routinen", c.get("/api/routines"))
    ok("Fällig", c.get("/api/routines/due"))
    ok("Zahlen", c.get("/api/routines/stats"))
    r = ok("Anlegen", c.post("/api/routines", json={"title": "Test-Routine",
                                                   "interval_days": 3})).json()
    ok("Erledigen", c.post(f"/api/routines/{r['id']}/done", json={}))
    ok("Löschen", c.delete(f"/api/routines/{r['id']}"))

    print("\n— Ideen und Projekte —")
    idea = ok("Idee", c.post("/api/ideas", json={"title": "App bauen"})).json()
    ok("Fragen", c.get("/api/ideas/questions"))
    check("Start während Karenz blockiert",
          c.post(f"/api/ideas/{idea['id']}/promote", json={}).status_code, 409)
    ok("Vertagen", c.post(f"/api/ideas/{idea['id']}/sleep?days=30"))
    ok("Projekte", c.get("/api/projects"))
    ok("Plätze", c.get("/api/projects/slots"))

    print("\n— Kaeufe —")
    buy = ok("Wunsch", c.post("/api/purchases", json={"title": "Monitor",
                                                     "price_eur": 300})).json()
    check("wartet eine Woche", buy["wait_hours"], 168)
    ok("Fragen und Budget", c.get("/api/purchases/meta"))
    ok("Antworten", c.post(f"/api/purchases/{buy['id']}/answer",
                           json={"answers": {"problem": "zu kleiner Schirm"}}))
    check("Recherche ohne Internet meldet sich freundlich",
          c.post(f"/api/purchases/{buy['id']}/research").status_code, 409)
    ok("Entscheiden", c.post(f"/api/purchases/{buy['id']}/decide",
                             json={"verdict": "verworfen"}))

    print("\n— Notizen, Menschen, Empfehlungen —")
    note = ok("Notiz", c.post("/api/notes", json={"body": "Steuernummer 123"})).json()
    ok("Suche", c.get("/api/notes?q=steuernummer"))
    ok("Notiz weg", c.delete(f"/api/notes/{note['id']}"))
    person = ok("Person", c.post("/api/people", json={"name": "Anna",
                                                     "cadence_days": 14})).json()
    ok("Gemeldet", c.post(f"/api/people/{person['id']}/contact", json={"what": "Telefon"}))
    ok("Faellige", c.get("/api/people/due"))
    rec = ok("Empfehlung", c.post("/api/recs", json={"title": "Dune",
                                                    "kind": "book"})).json()
    ok("Bewerten", c.patch(f"/api/recs/{rec['id']}", json={"status": "done",
                                                          "rating": 5}))
    ok("Sorten", c.get("/api/recs/meta"))

    print("\n— Anschub —")
    nudge = ok("Hinweis", c.get("/api/unblock/nudge")).json()
    check("er rechnet Signale mit", "signale" in nudge, True)
    step = ok("Einstieg", c.post("/api/unblock", json={"feeling": "keine Ahnung wo anfangen"})).json()
    check("es kommt genau ein Schritt", bool(step["schritt"]), True)
    check("mit einer Dauer unter sechs Minuten", step["dauer_min"] <= 5, True)
    ok("Ergebnis melden", c.post(f"/api/unblock/{step['id_log']}/outcome",
                                 json={"verdict": "geschafft"}))
    hist = ok("Verlauf", c.get("/api/unblock/history")).json()
    check("der Verlauf zählt mit", hist["zahlen"]["geschafft"], 1)

    print("\n— Einstellungen, Modelle, Muster —")
    ok("Einstellungen lesen", c.get("/api/settings"))
    ok("Einstellungen schreiben", c.post("/api/settings", json={"wip_limit": "4"}))
    check("und sie wirken", c.get("/api/settings").json()["wip_limit"], "4")
    ok("Modelle", c.get("/api/models"))
    ok("Muster", c.post("/api/profile"))
    ok("Protokoll", c.get("/api/events"))
    chat = ok("Chat ohne Modell", c.post("/api/chat", json={"message": "Hallo"})).json()
    check("er sagt, dass das Modell fehlt", "Modell" in chat["answer"], True)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Endpunkte antworten.")
