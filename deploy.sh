#!/usr/bin/env bash
# Kompass auf Unraid aufsetzen — ohne Docker Compose, ohne Dockge.
#
# Unraid bringt kein "docker compose" mit. Dieses Skript macht dasselbe, was
# die docker-compose.yml beschreibt, nur mit reinen docker-Befehlen. Es ist
# gefahrlos wiederholbar: der Container wird ersetzt, das Datenvolume nie
# angefasst.
#
#   ./deploy.sh                Image bauen und starten  (Standard)
#   ./deploy.sh --no-build     nur neu starten, ohne zu bauen
#   ./deploy.sh --own-ollama   eigenen Ollama-Container mitstarten
#   ./deploy.sh stop           Container anhalten und entfernen
#   ./deploy.sh logs           Logs verfolgen
#   ./deploy.sh status         Kurzueberblick
#
# Kompass benutzt normalerweise das Ollama, das schon fuer PULS laeuft. Dafuer
# legt das Skript ein gemeinsames Netz an und haengt beide Container hinein.
# Laeuft kein PULS auf der Kiste, hilft --own-ollama.
#
# Deine Daten liegen im Volume kompass-data und ueberleben alles ausser einem
# ausdruecklichen "docker volume rm kompass-data".

set -euo pipefail
# Achtung bei "set -e": Eine Zeile der Form  [ Bedingung ] && Aktion  liefert 1,
# wenn die Bedingung nicht zutrifft — und beendet damit das ganze Skript.
# Deshalb entweder ein richtiges "if" oder "|| true" anhaengen.
cd "$(dirname "$0")"

NET=kompass-ki
IMG=kompass:latest
CONTAINER=kompass
VOLUME=kompass-data

c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m•\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------- Einstellungen
if [ -f .env ]; then
    set -a; . ./.env; set +a
    c_ok "Einstellungen aus .env geladen"
else
    c_warn "Keine .env gefunden — es gelten die Standardwerte."
    c_warn "Anlegen mit:  cp .env.example .env"
fi

TZ="${TZ:-Europe/Berlin}"
KOMPASS_PORT="${KOMPASS_PORT:-1338}"
OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-puls-ollama}"
OLLAMA_URL="${OLLAMA_URL:-http://${OLLAMA_CONTAINER}:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
KOMPASS_TOKEN="${KOMPASS_TOKEN:-}"
ALLOW_WEB="${ALLOW_WEB:-1}"
SEARXNG_URL="${SEARXNG_URL:-}"
TMDB_API_KEY="${TMDB_API_KEY:-}"

OWN_OLLAMA=0
BUILD=1
for arg in "$@"; do
    case "$arg" in
        --no-build)   BUILD=0 ;;
        --own-ollama) OWN_OLLAMA=1 ;;
    esac
done

# ------------------------------------------------------------------ Unterbefehle
cmd="${1:-deploy}"

case "$cmd" in
  stop)
      for c in "$CONTAINER" kompass-ollama; do
          docker rm -f "$c" >/dev/null 2>&1 && c_ok "$c entfernt" || true
      done
      echo
      c_info "Das Volume $VOLUME ist unberuehrt."
      exit 0 ;;
  logs)
      exec docker logs -f --tail 100 "$CONTAINER" ;;
  status)
      docker ps --filter "name=kompass" --filter "name=$OLLAMA_CONTAINER" \
                --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
      echo
      if docker exec "$CONTAINER" python -c "import urllib.request,sys; \
             sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', \
             timeout=3).status==200 else 1)" >/dev/null 2>&1; then
          c_ok "Kompass antwortet."
      else
          c_warn "Kompass antwortet nicht."
      fi
      exit 0 ;;
esac

# ------------------------------------------------------------------------ Netz
if ! docker network inspect "$NET" >/dev/null 2>&1; then
    docker network create "$NET" >/dev/null
    c_ok "Netz $NET angelegt"
else
    c_ok "Netz $NET ist da"
fi

# -------------------------------------------------------------------- Ollama
if [ "$OWN_OLLAMA" = "1" ]; then
    if ! docker ps -a --format '{{.Names}}' | grep -qx kompass-ollama; then
        docker run -d --name kompass-ollama --restart unless-stopped \
            --network "$NET" \
            -e OLLAMA_MAX_LOADED_MODELS=1 -e OLLAMA_KEEP_ALIVE=30m \
            -e NVIDIA_VISIBLE_DEVICES="${OLLAMA_GPU:-}" \
            -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
            --runtime "${OLLAMA_RUNTIME:-runc}" \
            -v kompass-ollama-data:/root/.ollama \
            ollama/ollama:latest >/dev/null
        c_ok "Eigener Ollama-Container gestartet"
    else
        docker start kompass-ollama >/dev/null 2>&1 || true
        c_ok "Eigener Ollama-Container laeuft"
    fi
    OLLAMA_URL="http://kompass-ollama:11434"
elif docker ps -a --format '{{.Names}}' | grep -qx "$OLLAMA_CONTAINER"; then
    # Den vorhandenen Ollama ins gemeinsame Netz haengen. Er bleibt in seinem
    # eigenen Netz — PULS merkt davon nichts.
    if docker network inspect "$NET" --format '{{range .Containers}}{{.Name}} {{end}}' \
         | grep -qw "$OLLAMA_CONTAINER"; then
        c_ok "$OLLAMA_CONTAINER haengt schon im Netz $NET"
    else
        docker network connect "$NET" "$OLLAMA_CONTAINER" >/dev/null
        c_ok "$OLLAMA_CONTAINER ins Netz $NET gehaengt"
    fi
else
    c_warn "Container $OLLAMA_CONTAINER nicht gefunden."
    c_warn "Entweder PULS starten, oder hier mit --own-ollama einen eigenen nehmen."
    c_warn "Kompass laeuft auch ohne — dann eben ohne KI-Texte."
fi

# ---------------------------------------------------------------------- Volume
docker volume inspect "$VOLUME" >/dev/null 2>&1 || {
    docker volume create "$VOLUME" >/dev/null
    c_ok "Volume $VOLUME angelegt"
}

# ------------------------------------------------------------------------ Bauen
if [ "$BUILD" = "1" ]; then
    c_info "Baue $IMG …"
    docker build -q -t "$IMG" . >/dev/null
    c_ok "Image gebaut"
fi

# ---------------------------------------------------------------------- Starten
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --restart unless-stopped \
    --network "$NET" \
    -p "${KOMPASS_PORT}:8000" \
    -e TZ="$TZ" \
    -e OLLAMA_URL="$OLLAMA_URL" \
    -e OLLAMA_MODEL="$OLLAMA_MODEL" \
    -e EMBED_MODEL="$EMBED_MODEL" \
    -e KOMPASS_TOKEN="$KOMPASS_TOKEN" \
    -e ALLOW_WEB="$ALLOW_WEB" \
    -e SEARXNG_URL="$SEARXNG_URL" \
    -e TMDB_API_KEY="$TMDB_API_KEY" \
    -v "$VOLUME":/data \
    "$IMG" >/dev/null
c_ok "Kompass laeuft auf Port $KOMPASS_PORT"

echo
c_info "Oberflaeche:  http://$(hostname -i 2>/dev/null | awk '{print $1}'):${KOMPASS_PORT}"
c_info "Logs:         ./deploy.sh logs"
if [ -n "$EMBED_MODEL" ]; then
    echo
    c_info "Fuer die semantische Notizsuche fehlt eventuell noch das kleine"
    c_info "Einbettungsmodell. Einmalig holen:"
    if [ "$OWN_OLLAMA" = "1" ]; then
        c_info "    docker exec kompass-ollama ollama pull $EMBED_MODEL"
    else
        c_info "    docker exec $OLLAMA_CONTAINER ollama pull $EMBED_MODEL"
    fi
fi
