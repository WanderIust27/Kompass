"""Zentrale Konfiguration — alles über Umgebungsvariablen steuerbar."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("KOMPASS_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "kompass.db"

# Standardmäßig redet Kompass mit dem Ollama, das schon für PULS läuft.
# Die beiden Container müssen dafür im selben Docker-Netz hängen —
# darum kümmert sich deploy.sh.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://puls-ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))
# Kleines Modell nur für die semantische Notizsuche (~270 MB).
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# Optionaler Schutz: wenn gesetzt, will die API diesen Token sehen.
TOKEN = os.environ.get("KOMPASS_TOKEN", "").strip()

# Internetzugang für Kaufrecherche und Empfehlungen.
ALLOW_WEB = os.environ.get("ALLOW_WEB", "1") not in ("0", "false", "no", "")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "").rstrip("/")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()

TZ = os.environ.get("TZ", "Europe/Berlin")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
