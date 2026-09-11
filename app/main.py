"""Kompass — dein lokaler Alltagsassistent."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers.api import router
from .services import scheduler
from .services.ollama_client import (OllamaUnavailable, is_available,
                                     model_present, pull_model)
from .services.websearch import WebDisabled
from .version import BUILT_AT, VERSION

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("kompass")

STATIC_DIR = Path(__file__).parent / "static"


def _ensure_model() -> None:
    """Beim Start prüfen, ob das Modell da ist — sonst ziehen.

    Bei geteiltem Ollama ist es meistens schon da, weil PULS es benutzt.
    Dann kostet das hier nichts.
    """
    try:
        if is_available() and not model_present():
            pull_model()
    except Exception as e:
        log.warning("Modell-Download fehlgeschlagen (später erneut möglich): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    threading.Thread(target=_ensure_model, daemon=True).start()
    scheduler.start()
    log.info("Kompass läuft. Version %s (Stand %s)", VERSION, BUILT_AT)
    yield
    scheduler.shutdown()


app = FastAPI(title="Kompass", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Fehler einmal zentral übersetzen statt in jeder Route zu wiederholen.
@app.exception_handler(KeyError)
def _not_found(request: Request, exc: KeyError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc).strip("'\"")})


@app.exception_handler(ValueError)
def _bad_request(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(PermissionError)
def _blocked(request: Request, exc: PermissionError) -> JSONResponse:
    """Das ist der Fall 'Regel greift' — kein Fehler, sondern der Punkt."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(WebDisabled)
def _no_web(request: Request, exc: WebDisabled) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(OllamaUnavailable)
def _no_model(request: Request, exc: OllamaUnavailable) -> JSONResponse:
    """Ohne Modell bleibt Kompass bedienbar — er sagt nur, was fehlt."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Das Modell antwortet gerade nicht. Läuft der "
                           f"Ollama-Container? ({exc})"})


@app.get("/")
def index() -> HTMLResponse:
    """Die Oberfläche, mit Versionsstempel an den statischen Dateien.

    Ohne den lädt der Browser nach einem Update die alte app.js aus seinem
    Cache weiter — die Datei heißt ja gleich.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{V}}", VERSION))


@app.get("/manifest.json")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.json")


@app.get("/sw.js")
def service_worker() -> Response:
    js = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(js.replace("{{V}}", VERSION),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}
