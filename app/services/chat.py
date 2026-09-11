"""Das Gespräch mit Kompass.

Der Chat sieht denselben Zustand wie das Briefing — sonst müsste man ihm
erst erzählen, was ohnehin in der Datenbank steht. Er darf nichts von sich
aus anlegen; wer etwas eintragen will, wirft es in die Inbox. Das hält die
Grenze klar: Der Chat denkt mit, die Inbox verändert.
"""
from __future__ import annotations

from typing import Any

from ..db import get_db, rows_to_dicts
from . import briefing, notes
from .ollama_client import OllamaUnavailable, chat as ollama_chat

HISTORY = 10


def history(limit: int = 40) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return list(reversed(rows_to_dicts(rows)))


def send(message: str) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        raise ValueError("Leere Nachricht.")
    with get_db() as db:
        db.execute("INSERT INTO chat_messages(role, content) VALUES('user',?)",
                   (message,))

    ctx = briefing.context()
    digest = briefing._digest(ctx)
    # Passende Notizen mitgeben — dann kann er auf Gemerktes zurückgreifen.
    found = notes.search(message, limit=3)
    if found:
        digest += "\n\nNotizen, die dazu passen könnten:\n" + "\n".join(
            f"- {n['title']}: {(n['body'] or '')[:300]}" for n in found)

    system = (briefing.system_prompt()
              + "\n\nDu bekommst den aktuellen Stand mitgeliefert. Nutze ihn, wenn er "
                "zur Frage passt, und schweig darüber, wenn nicht. Du kannst nichts "
                "selbst eintragen — wenn etwas gespeichert werden soll, sag ihm, er "
                "solle es in die Inbox werfen."
              + "\n\nAktueller Stand:\n" + digest)

    messages = [{"role": m["role"], "content": m["content"]}
                for m in history(HISTORY * 2)[-HISTORY:]]
    try:
        answer = ollama_chat(messages, system=system)
    except OllamaUnavailable as e:
        answer = (f"Ich komme gerade nicht ans Modell heran ({e}). "
                  f"Schau mal, ob der Ollama-Container läuft.")
    with get_db() as db:
        db.execute("INSERT INTO chat_messages(role, content) VALUES('assistant',?)",
                   (answer,))
    return {"answer": answer, "history": history(HISTORY * 2)}


def clear() -> None:
    with get_db() as db:
        db.execute("DELETE FROM chat_messages")
