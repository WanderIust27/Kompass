"""Dünner Client fuer die lokale Ollama-Instanz.

Kompass teilt sich das Ollama mit PULS. Das heißt auch: das Modell kann
gerade fuer die andere App im Speicher liegen und ein paar Sekunden brauchen,
bis es antwortet. Deshalb sind die Zeitlimits großzügig.
"""
from __future__ import annotations

import json
import logging
import struct
from typing import Any, Sequence

import httpx

from ..config import EMBED_MODEL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
from ..db import get_setting

log = logging.getLogger("kompass.ollama")

# Auswahl fuer die Oberfläche. Größen sind Richtwerte fuer Q4; die
# Einschätzung zur Geschwindigkeit gilt fuer eine 8-GB-Karte.
MODEL_PRESETS = [
    {"name": "qwen3:8b", "label": "Qwen 3 · 8B", "size_gb": 4.7,
     "speed": "flüssig",
     "note": "Empfohlen und dasselbe Modell, das PULS benutzt — dann liegt nur "
             "eines auf der Karte. Bestes Deutsch in dieser Größe, argumentiert "
             "ordentlich genug fuer Kaufberatung und Ideenbewertung."},
    {"name": "qwen3:4b", "label": "Qwen 3 · 4B", "size_gb": 2.8,
     "speed": "schnell",
     "note": "Etwa doppelt so schnell. Merklich schlichter, wenn er abwägen "
             "soll — fuer Einsortieren und kurze Rückmeldungen aber genug."},
    {"name": "gemma3:4b", "label": "Gemma 3 · 4B", "size_gb": 2.6,
     "speed": "schnell",
     "note": "Formuliert oft natürlicher als Qwen, denkt dafuer weniger "
             "strukturiert. Angenehm fuer Briefings."},
    {"name": "llama3.2:3b", "label": "Llama 3.2 · 3B", "size_gb": 2.0,
     "speed": "sehr schnell",
     "note": "Der Sparsame. Lässt noch Platz fuer ein zweites Modell auf der "
             "Karte, bei längeren Begründungen merkt man die Größe."},
]


class OllamaUnavailable(Exception):
    pass


def active_model() -> str:
    """In der Oberfläche gewähltes Modell, sonst der Wert aus der Umgebung."""
    return get_setting("ollama_model", "") or OLLAMA_MODEL


def is_available() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def installed_models() -> list[dict[str, Any]]:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return r.json().get("models", []) or []
    except httpx.HTTPError:
        return []


def model_present(name: str | None = None) -> bool:
    name = name or active_model()
    names = [m.get("name", "") for m in installed_models()]
    if name in names:
        return True
    base = name.split(":")[0]
    return any(n.split(":")[0] == base for n in names)


_pull_state: dict[str, Any] = {"model": None, "status": "idle", "percent": 0,
                               "error": None}


def pull_state() -> dict[str, Any]:
    return dict(_pull_state)


def pull_model(name: str | None = None) -> None:
    """Modell herunterladen. Blockiert — gehört in einen Hintergrund-Thread."""
    name = name or active_model()
    _pull_state.update({"model": name, "status": "laden", "percent": 0, "error": None})
    log.info("Lade Modell %s.", name)
    try:
        with httpx.stream("POST", f"{OLLAMA_URL}/api/pull",
                          json={"name": name}, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("error"):
                    _pull_state.update({"status": "fehler", "error": msg["error"]})
                    log.error("Download von %s fehlgeschlagen: %s", name, msg["error"])
                    return
                total, done = msg.get("total"), msg.get("completed")
                if total and done:
                    _pull_state["percent"] = round(done / total * 100)
                status = msg.get("status", "")
                _pull_state["detail"] = status
                if "success" in status:
                    _pull_state.update({"status": "fertig", "percent": 100})
                    log.info("Modell %s bereit.", name)
                    return
        _pull_state["status"] = "fertig"
    except httpx.HTTPError as e:
        _pull_state.update({"status": "fehler", "error": str(e)})
        log.error("Download von %s fehlgeschlagen: %s", name, e)


def generate(prompt: str, system: str | None = None, json_mode: bool = False,
             temperature: float = 0.7, num_ctx: int = 8192) -> str:
    """Eine Antwort vom lokalen Modell holen."""
    payload: dict[str, Any] = {
        "model": active_model(),
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload,
                       timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        return _strip_thinking((r.json().get("response") or "").strip())
    except httpx.HTTPError as e:
        raise OllamaUnavailable(f"Ollama nicht erreichbar oder Fehler: {e}") from e


def chat(messages: list[dict[str, str]], system: str | None = None,
         temperature: float = 0.6, num_ctx: int = 8192) -> str:
    """Mehrzügiges Gespräch — fuer den Chat-Reiter."""
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    payload = {"model": active_model(), "messages": msgs, "stream": False,
               "options": {"temperature": temperature, "num_ctx": num_ctx}}
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        return _strip_thinking(
            ((r.json().get("message") or {}).get("content") or "").strip())
    except httpx.HTTPError as e:
        raise OllamaUnavailable(f"Ollama nicht erreichbar oder Fehler: {e}") from e


def generate_json(prompt: str, system: str | None = None,
                  temperature: float = 0.3) -> dict[str, Any]:
    """JSON-Antwort erzwingen und robust parsen."""
    text = generate(prompt, system=system, json_mode=True, temperature=temperature)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise OllamaUnavailable(f"Modell lieferte kein gültiges JSON: {text[:200]}")


def _strip_thinking(text: str) -> str:
    """Qwen3 denkt in <think>-Blöcken. Die will hier niemand lesen."""
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>") + len("</think>")
        text = (text[:start] + text[end:]).strip()
    return text


# ------------------------------------------------------------- Einbettungen

def embed_model() -> str:
    return EMBED_MODEL


def embed(texts: Sequence[str]) -> list[list[float]]:
    """Texte in Vektoren verwandeln — fuer die semantische Notizsuche.

    Neuere Ollama-Versionen können /api/embed mit mehreren Texten auf einmal,
    ältere nur /api/embeddings mit einem. Beides wird bedient.
    """
    if not EMBED_MODEL:
        raise OllamaUnavailable("Kein Einbettungsmodell gesetzt.")
    items = [t for t in texts]
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/embed",
                       json={"model": EMBED_MODEL, "input": items},
                       timeout=OLLAMA_TIMEOUT)
        if r.status_code == 404:
            raise httpx.HTTPStatusError("alt", request=r.request, response=r)
        r.raise_for_status()
        vecs = r.json().get("embeddings") or []
        if vecs:
            return [_normalise(v) for v in vecs]
    except httpx.HTTPError:
        pass
    out: list[list[float]] = []
    for text in items:
        try:
            r = httpx.post(f"{OLLAMA_URL}/api/embeddings",
                           json={"model": EMBED_MODEL, "prompt": text},
                           timeout=OLLAMA_TIMEOUT)
            r.raise_for_status()
            out.append(_normalise(r.json().get("embedding") or []))
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"Einbettung fehlgeschlagen: {e}") from e
    return out


def _normalise(vec: Sequence[float]) -> list[float]:
    """Auf Länge 1 bringen — dann ist das Skalarprodukt die Aehnlichkeit."""
    total = sum(v * v for v in vec) ** 0.5
    if not total:
        return list(vec)
    return [v / total for v in vec]


def pack_vector(vec: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))
