"""Tests der Regeln, die Kompass ausmachen.

Geprueft wird genau das, was weh tut, wenn es falsch ist: Wartefristen,
Karenzzeit, das Projektlimit, der Haushaltsrhythmus und der Tagesplan.
Alles läuft gegen eine Wegwerf-Datenbank, ohne Modell und ohne Netz.

Aufruf:  python3 tests/test_rules.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["KOMPASS_DATA_DIR"] = tempfile.mkdtemp(prefix="kompass-test-")
os.environ["OLLAMA_URL"] = "http://127.0.0.1:1"      # bewusst tot
os.environ["ALLOW_WEB"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db, init_db, set_setting, today_str      # noqa: E402
from app.services import (notes, planner, projects, purchases,  # noqa: E402
                          routines, tasks, triage)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


def check_raises(name, exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        print(f"OK   {name}: {exc.__name__} wie erwartet")
        return
    except Exception as e:                                  # falscher Fehler
        print(f"FAIL {name}: {type(e).__name__} statt {exc.__name__}")
        failures.append(name)
        return
    print(f"FAIL {name}: kein Fehler, aber {exc.__name__} erwartet")
    failures.append(name)


init_db()

# --- Kaufberatung: gestaffelte Wartefrist --------------------------------
print("\n— Wartefristen —")
check("unter der Schwelle wartet nicht", purchases.wait_hours_for(9.99), 0)
check("ab 20 Euro 48 Stunden", purchases.wait_hours_for(25), 48)
check("ab 100 Euro eine Woche", purchases.wait_hours_for(150), 168)

klein = purchases.create({"title": "Kabel", "price_eur": 8})
check("Kleinkram sofort entscheidbar", klein["status"], "ready")
gross = purchases.create({"title": "Kopfhörer", "price_eur": 180})
check("Teures wartet", gross["status"], "waiting")
check("und zwar 7 Tage", gross["wait_hours"], 168)

# Wartefrist künstlich ablaufen lassen
with get_db() as db:
    db.execute("UPDATE purchases SET wait_until='2000-01-01 00:00:00' WHERE id=?",
               (gross["id"],))
check("abgelaufene Frist wird frei", purchases.ripen(), 1)
check("danach steht die Entscheidung an", purchases.get(gross["id"])["status"], "ready")

gekauft = purchases.decide(gross["id"], "gekauft", 150)
check("Kauf merkt sich den echten Preis", gekauft["bought_price"], 150.0)
check("und fragt später nach", bool(gekauft["usage_check_at"]), True)
check("Budget zählt den Kauf", purchases.budget_state()["spent"], 150.0)

verworfen = purchases.decide(klein["id"], "verworfen")
check("Verworfenes zählt als gespart", purchases.stats()["gespart"], 8.0)

# --- Ideenbremse ---------------------------------------------------------
print("\n— Karenzzeit und Projektlimit —")
idee = projects.add_idea("Newsletter starten")
check("Karenz beträgt 7 Tage", idee["days_left"], 7)
check("und sie ist nicht reif", idee["is_ripe"], False)
check_raises("Start während der Karenz wird verweigert", PermissionError,
             projects.promote, idee["id"])

with get_db() as db:
    db.execute("UPDATE ideas SET ripe_at=? WHERE id=?",
               ((date.today() - timedelta(days=1)).isoformat(), idee["id"]))
check("reife Ideen werden erkannt", projects.ripen(), 1)

for i in range(3):
    projects.add_project(f"Projekt {i}")
check("drei Plätze sind belegt", projects.slots()["free"], 0)
check_raises("das vierte Projekt wird abgelehnt", PermissionError,
             projects.add_project, "Noch eins")
mit_grund = projects.add_project("Noch eins", override_reason="Deadline im Beruf")
check("mit Begründung geht es doch", mit_grund["status"], "active")
check("und die Begründung steht drin",
      mit_grund["override_reason"], "Deadline im Beruf")

projects.update_project(mit_grund["id"], {"status": "done"})
check("Abschliessen macht einen Platz frei", projects.slots()["used"], 3)

# --- Haushalt ------------------------------------------------------------
print("\n— Haushaltsrhythmus —")
routine = routines.create({"title": "Bad putzen", "interval_days": 7,
                           "duration_min": 20})
erledigt = routines.complete(routine["id"])
check("Rhythmus zählt ab Erledigung",
      erledigt["next_due"], (date.today() + timedelta(days=7)).isoformat())
check("Streak steigt", erledigt["streak"], 1)

zweite = routines.create({"title": "Staubsaugen", "interval_days": 4,
                          "duration_min": 15})
for _ in range(2):
    routines.snooze(zweite["id"])
check("zweimal schieben ändert nichts am Rhythmus",
      routines.get(zweite["id"])["interval_days"], 4.0)
gestreckt = routines.snooze(zweite["id"])
check("beim dritten Mal streckt Kompass selbst",
      gestreckt["interval_days"], 6.0)
check("und faengt wieder bei null an", gestreckt["skips"], 0)

# --- Aufgaben und Tagesplan ---------------------------------------------
print("\n— Aufgaben und Tagesplan —")
gestern = (date.today() - timedelta(days=1)).isoformat()
alt = tasks.create({"title": "Liegengebliebenes", "est_min": 10})
tasks.update(alt["id"], {"planned_day": gestern})
check("Offenes von gestern wandert auf heute", tasks.roll_over(), 1)
check("und traegt heute als Tag", tasks.get(alt["id"])["planned_day"], today_str())
check("das Verschieben wird mitgezählt", tasks.get(alt["id"])["snoozes"], 1)

set_setting("capacity_json", '{"Mo":30,"Di":30,"Mi":30,"Do":30,"Fr":30,"Sa":30,"So":30}')
check("Kapazitaet kommt aus den Einstellungen", planner.capacity(), 30)
tasks.create({"title": "Langer Brocken", "est_min": 200})
ueberfaellig = tasks.create({"title": "Steuer", "est_min": 120,
                             "due_date": "2020-01-01"})
plan = planner.plan()
titel = [t["title"] for t in plan["tasks"]]
check("Überfälliges steht drin, egal wie lang", "Steuer" in titel, True)
check("Unpassendes landet im Ueberlauf",
      "Langer Brocken" in [t["title"] for t in plan["overflow"]], True)

# --- Inbox ohne Modell ---------------------------------------------------
print("\n— Inbox ohne Modell —")
check("Kauf wird am Preis erkannt",
      triage.classify("neue Kopfhörer 180 euro")["art"], "kauf")
check("Idee wird am Wort erkannt",
      triage.classify("Idee: einen Podcast machen")["art"], "idee")
check("Wiederkehrendes wird Routine",
      triage.classify("jeden Sonntag Wäsche waschen")["art"], "routine")
check("alles andere ist eine Aufgabe",
      triage.classify("Rechnung an Vermieter schicken")["art"], "aufgabe")

wurf = triage.add("Zahnarzt anrufen")
triage.suggest(wurf["id"])
angelegt = triage.apply(wurf["id"])
check("aus dem Zuruf wird eine Aufgabe", angelegt["kind"], "aufgabe")
check("und die Inbox ist sie los", triage.pending_count(), 0)

# --- Notizen -------------------------------------------------------------
print("\n— Notizen —")
notes.create({"body": "Der Router steht im Schrank, Passwort klebt hinten drauf."})
notes.create({"body": "Fahrradschloss-Code ist der Geburtstag von Oma."})
treffer = notes.search("router")
check("Volltextsuche findet die Notiz", len(treffer), 1)
check("auch bei Wortanfang", len(notes.search("fahrrad")), 1)
check("ohne Treffer bleibt es leer", len(notes.search("hubschrauber")), 0)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Regeln greifen.")
