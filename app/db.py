"""SQLite-Zugriff — bewusst schlank, ohne ORM.

Eine Datei, eine Sperre, klare Tabellen. Alles, was Kompass über dich weiß,
steht hier und nirgends sonst.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from .config import DB_PATH, ensure_dirs

_lock = threading.Lock()

SCHEMA = """
-- Alles, was du reinwirfst, landet zuerst hier. Ungefiltert, ohne Pflichtfelder.
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'new',      -- new | sorted | dismissed
    kind TEXT,                               -- task|idea|note|purchase|person|rec|routine
    suggestion_json TEXT,                    -- was das Modell daraus lesen würde
    target_kind TEXT,
    target_id INTEGER,
    sorted_at TEXT
);

-- Ein Projekt ist etwas, das mehrere Schritte braucht. Davon sind nur
-- wenige gleichzeitig erlaubt (WIP-Limit) — das ist der Kern der Bremse.
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    why TEXT,                                -- woran man merkt, dass es fertig ist
    status TEXT NOT NULL DEFAULT 'active',   -- active | paused | done | dropped
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    done_at TEXT,
    deadline TEXT,
    next_action TEXT,
    note TEXT,
    from_idea_id INTEGER,
    override_reason TEXT                     -- falls das WIP-Limit gebrochen wurde
);

-- Der Parkplatz. Jede Idee liegt erst eine Karenzzeit hier, bevor sie
-- überhaupt zur Abstimmung steht.
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ripe_at TEXT NOT NULL,                   -- Ende der Karenz
    status TEXT NOT NULL DEFAULT 'parked',   -- parked | ripe | promoted | dropped | later
    review_json TEXT,                        -- deine Antworten im Bewertungsritual
    ai_take TEXT,                            -- Einschätzung des Modells
    decided_at TEXT,
    project_id INTEGER,
    revived INTEGER NOT NULL DEFAULT 0       -- wie oft schon wiederbelebt
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    area TEXT NOT NULL DEFAULT 'alltag',     -- alltag|haushalt|projekt|menschen|admin
    status TEXT NOT NULL DEFAULT 'open',     -- open | done | dropped
    est_min INTEGER NOT NULL DEFAULT 15,
    energy TEXT NOT NULL DEFAULT 'mittel',   -- niedrig | mittel | hoch
    context TEXT,                            -- zuhause|laptop|unterwegs|telefon
    due_date TEXT,
    planned_day TEXT,
    priority INTEGER NOT NULL DEFAULT 2,     -- 1 wichtig | 2 normal | 3 irgendwann
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    done_at TEXT,
    snoozes INTEGER NOT NULL DEFAULT 0,
    routine_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 100
);

-- Haushalt. Der Rhythmus zählt ab der letzten Erledigung, nicht ab Kalender —
-- sonst hängt nach einer vollen Woche alles gleichzeitig über dir.
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    room TEXT,
    interval_days REAL NOT NULL DEFAULT 7,
    duration_min INTEGER NOT NULL DEFAULT 10,
    energy TEXT NOT NULL DEFAULT 'mittel',
    last_done TEXT,
    next_due TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    streak INTEGER NOT NULL DEFAULT 0,
    skips INTEGER NOT NULL DEFAULT 0,        -- wie oft zuletzt weggedrückt
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS routine_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    done_at TEXT NOT NULL DEFAULT (datetime('now')),
    note TEXT
);

-- Kaufberatung: Wartefrist, Verhör, Recherche, Budget, spätere Ehrlichkeit.
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    price_eur REAL,
    url TEXT,
    category TEXT,
    reason TEXT,                             -- warum du es willst
    status TEXT NOT NULL DEFAULT 'waiting',  -- waiting|ready|bought|dropped
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    wait_until TEXT,
    wait_hours INTEGER,
    answers_json TEXT,                       -- Antworten aus dem Verhör
    research_json TEXT,                      -- Fundstücke aus dem Netz
    ai_take TEXT,
    decided_at TEXT,
    bought_at TEXT,
    bought_price REAL,
    usage_check_at TEXT,                     -- wann er nachfragt, ob du es nutzt
    usage_verdict TEXT                       -- oft | manchmal | nie
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT NOT NULL,
    tags TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body);
-- Vektoren für die semantische Suche: float32, auf Länge 1 normiert,
-- damit das Skalarprodukt direkt die Aehnlichkeit ist.
CREATE TABLE IF NOT EXISTS note_vectors (
    note_id INTEGER PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    birthday TEXT,                           -- YYYY-MM-DD oder --MM-DD
    cadence_days INTEGER,                    -- gewünschter Melde-Rhythmus
    last_contact TEXT,
    note TEXT,
    tags TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS people_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    what TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'book',       -- book|movie|series|podcast|game|other
    title TEXT NOT NULL,
    creator TEXT,
    year INTEGER,
    why TEXT,
    source TEXT,                             -- ich | kompass | netz
    status TEXT NOT NULL DEFAULT 'queued',   -- queued|doing|done|dropped
    rating INTEGER,                          -- 1..5, nach dem Konsumieren
    url TEXT,
    external_json TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    done_at TEXT
);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    slot TEXT NOT NULL,                      -- morning | evening
    text TEXT NOT NULL,
    computed INTEGER NOT NULL DEFAULT 0,     -- 1 = gerechnet, weil kein Modell da war
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(day, slot)
);

CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL UNIQUE,
    mood INTEGER,                            -- 1..5
    energy INTEGER,                          -- 1..5
    note TEXT,
    planned_count INTEGER,
    done_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Was Kompass über dich gelernt hat. Teils gerechnet, teils vom Modell.
CREATE TABLE IF NOT EXISTS profile_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL,
    value_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,                      -- user | assistant
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Protokoll dessen, was Kompass von sich aus getan hat. Damit Umplanen
-- nachvollziehbar bleibt und nicht wie Zauberei wirkt.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);

-- Der Anschub: jedes Mal, wenn nichts mehr ging, und was daraus wurde.
-- Daraus lernt Kompass, welcher Einstieg bei dir wirklich zieht.
CREATE TABLE IF NOT EXISTS unblock_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    feeling TEXT,                            -- was du gesagt hast, wenn du etwas gesagt hast
    signals_json TEXT,                       -- woran Kompass die Blockade gesehen hat
    step TEXT NOT NULL,                      -- der eine Schritt
    kind TEXT,                               -- task | routine | frei
    ref_id INTEGER,
    minutes INTEGER,
    why TEXT,
    ignore_json TEXT,                        -- was gerade ausdrücklich liegenbleiben darf
    outcome TEXT                             -- geschafft | anders | nichts
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, planned_day);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_routines_due ON routines(active, next_due);
CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at DESC);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    # --- Ideen- und Projektbremse -------------------------------------
    "idea_cooldown_days": "7",       # so lange liegt jede Idee auf dem Parkplatz
    "wip_limit": "3",                # so viele Projekte dürfen gleichzeitig laufen
    # --- Kaufberatung --------------------------------------------------
    "buy_threshold_small": "20",     # ab hier wird gewartet
    "buy_wait_small_h": "48",
    "buy_threshold_big": "100",      # ab hier länger
    "buy_wait_big_h": "168",
    "buy_budget_month": "",          # leer = kein Budget gesetzt
    "buy_usage_check_days": "30",    # so lange nach dem Kauf fragt er nach
    # --- Tagesrhythmus -------------------------------------------------
    "morning_hour": "7",
    "evening_hour": "21",
    # Wie viele Minuten du an einem Wochentag realistisch für Aufgaben und
    # Haushalt hast. Wird in den Einstellungen gesetzt.
    "capacity_json": json.dumps({"Mo": 60, "Di": 60, "Mi": 60, "Do": 60,
                                 "Fr": 60, "Sa": 120, "So": 90}),
    "work_start": "09:00",
    "work_end": "17:30",
    # --- Ton und Darstellung -------------------------------------------
    "tone": "direkt",                # direkt | freundlich | trocken
    # --- Anschub bei Blockade ------------------------------------------
    "nudge_hour": "14",              # ab dieser Stunde fällt "heute nichts" auf
    "unblock_model": "",             # eigenes Modell für den Anschub; leer = dasselbe
    "user_name": "",
    "ui_scale": "100",
    "ollama_model": "",              # leer = Wert aus der Umgebung
    "embed_enabled": "1",
}

# Startplan Haushalt. Bewusst kleinteilig: "Bad putzen" ist eine Stunde und
# wird verschoben, "Waschbecken und Spiegel" sind fünf Minuten und werden
# gemacht. Alles hier ist in der App änderbar und löschbar.
SEED_ROUTINES: list[tuple[str, str, float, int, str]] = [
    # (Titel, Raum, Intervall in Tagen, Dauer, Energie)
    ("Abwasch / Spülmaschine ausräumen", "Küche", 1, 10, "niedrig"),
    ("Arbeitsflächen abwischen", "Küche", 1, 5, "niedrig"),
    ("Kühlschrank durchsehen", "Küche", 14, 15, "niedrig"),
    ("Herd und Dunstabzug", "Küche", 14, 20, "mittel"),
    ("Müll rausbringen", "Küche", 4, 5, "niedrig"),
    ("Altpapier und Glas wegbringen", "Küche", 21, 15, "mittel"),
    ("Waschbecken und Spiegel", "Bad", 3, 5, "niedrig"),
    ("WC putzen", "Bad", 7, 10, "mittel"),
    ("Dusche putzen", "Bad", 7, 15, "mittel"),
    ("Handtücher wechseln", "Bad", 7, 5, "niedrig"),
    ("Staubsaugen", "Wohnung", 4, 15, "mittel"),
    ("Boden wischen", "Wohnung", 14, 20, "mittel"),
    ("Staub wischen", "Wohnung", 14, 15, "niedrig"),
    ("Schreibtisch leerräumen", "Wohnung", 7, 10, "niedrig"),
    ("Pflanzen gießen", "Wohnung", 4, 5, "niedrig"),
    ("Fenster putzen", "Wohnung", 90, 45, "hoch"),
    ("Wäsche waschen und aufhängen", "Wäsche", 4, 15, "niedrig"),
    ("Bettwäsche wechseln", "Wäsche", 14, 15, "mittel"),
    ("Wäsche zusammenlegen und wegräumen", "Wäsche", 7, 20, "niedrig"),
    ("Einkauf und Vorräte", "Versorgung", 7, 45, "mittel"),
]


# Spalten, die zu einer bestehenden Datenbank hinzukommen können. CREATE TABLE
# IF NOT EXISTS ergänzt keine Spalten — das muss ALTER TABLE tun. Die Liste darf
# wachsen; jeder Eintrag wird nur angelegt, wenn er noch fehlt.
COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("briefings", "computed", "INTEGER NOT NULL DEFAULT 0"),
]


def init_db() -> None:
    ensure_dirs()
    with get_db() as db:
        db.executescript(SCHEMA)
        _migrate(db)
        for key, value in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)",
                       (key, value))
        _seed_routines(db)


def _migrate(db: sqlite3.Connection) -> None:
    """Fehlende Spalten nachrüsten, ohne bestehende Daten anzufassen."""
    tables = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for table, column, coltype in COLUMN_MIGRATIONS:
        if table not in tables:
            continue
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _seed_routines(db: sqlite3.Connection) -> None:
    """Startplan nur einmal anlegen.

    Ueber den Merker in settings, nicht über "Tabelle ist leer" — sonst
    kämen gelöschte Routinen beim nächsten Start alle wieder.
    """
    row = db.execute("SELECT value FROM settings WHERE key='routines_seeded'"
                     ).fetchone()
    if row and row["value"] == "1":
        return
    # Nicht alles auf den ersten Tag legen: Zwanzig fällige Punkte am Tag eins
    # sind keine Liste, sondern eine Wand. Jede Routine startet um ein paar Tage
    # versetzt — innerhalb ihres eigenen Rhythmus, damit sich das einpendelt.
    for i, (title, room, interval, minutes, energy) in enumerate(SEED_ROUTINES):
        offset = i % max(1, min(int(interval), 7))
        db.execute(
            """INSERT INTO routines(title, room, interval_days, duration_min,
                                    energy, next_due, sort_order)
               VALUES(?,?,?,?,?,?,?)""",
            (title, room, interval, minutes, energy,
             (date.today() + timedelta(days=offset)).isoformat(), i * 10))
    db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('routines_seeded','1')")


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Datenbankverbindung mit Sperre.

    Achtung: Die Sperre ist nicht reentrant. Innerhalb eines offenen get_db()
    darf nichts aufgerufen werden, das seinerseits die Datenbank öffnet —
    auch nicht get_setting(). Werte, die in einer Schleife gebraucht werden,
    vorher bestimmen.
    """
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def get_int(key: str, default: int) -> int:
    try:
        return int(float(get_setting(key, "") or default))
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float) -> float:
    try:
        return float(get_setting(key, "") or default)
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: str) -> None:
    with get_db() as db:
        db.execute("INSERT INTO settings(key, value) VALUES(?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))


def all_settings() -> dict[str, str]:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def log_event(kind: str, text: str) -> None:
    """Was Kompass selbst getan hat — für die Zeile 'was ich verändert habe'."""
    with get_db() as db:
        db.execute("INSERT INTO events(kind, text) VALUES(?,?)", (kind, text))


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)


# ---------------------------------------------------------------- Zeitdinge

def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def day_plus(days: float, start: date | None = None) -> str:
    return ((start or date.today()) + timedelta(days=round(days))).isoformat()


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def weekday_key(d: date | None = None) -> str:
    return WEEKDAYS[(d or date.today()).weekday()]
