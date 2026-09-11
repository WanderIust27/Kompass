#!/bin/sh
# Kompass aktualisieren: neuen Stand von GitHub holen und neu starten.
#
#   ./update.sh              aktualisieren und deployen
#   ./update.sh --no-deploy  nur die Dateien austauschen
#
# Angefasst werden ausschliesslich die Programmdateien. Deine .env bleibt
# stehen (sie liegt nicht im Paket), und das Volume kompass-data — also
# Aufgaben, Notizen, Routinen, alles — ruehrt das Skript nicht an.

REPO="${KOMPASS_REPO:-WanderIust27/Kompass}"
BRANCH="${KOMPASS_BRANCH:-main}"

# Das Skript ueberschreibt sich beim Kopieren selbst. Die Shell liest ihre
# Datei aber waehrend der Ausfuehrung weiter nach — deshalb zuerst nach /tmp
# ausweichen und von dort arbeiten.
if [ "${KOMPASS_RELOCATED:-}" != "1" ]; then
    tmp_self=$(mktemp /tmp/kompass-update.XXXXXX) || exit 1
    cat "$0" > "$tmp_self" && chmod +x "$tmp_self" || exit 1
    KOMPASS_RELOCATED=1 KOMPASS_TARGET="$(pwd)"
    export KOMPASS_RELOCATED KOMPASS_TARGET
    "$tmp_self" "$@"
    status=$?
    rm -f "$tmp_self"
    exit $status
fi

cd "$KOMPASS_TARGET" || exit 1

c_ok()   { printf '\033[32m  ✓\033[0m %s\n' "$1"; }
c_info() { printf '\033[36m  →\033[0m %s\n' "$1"; }
c_err()  { printf '\033[31m  ✗\033[0m %s\n' "$1" >&2; }

echo
c_info "Aktualisiere Kompass in $KOMPASS_TARGET"
c_info "Quelle: $REPO ($BRANCH)"

command -v unzip >/dev/null || { c_err "unzip nicht gefunden."; exit 1; }

work=$(mktemp -d /tmp/kompass-src.XXXXXX) || exit 1
trap 'rm -rf "$work"' EXIT

url="https://codeload.github.com/$REPO/zip/refs/heads/$BRANCH"
if command -v curl >/dev/null; then
    curl -fsSL "$url" -o "$work/src.zip" || { c_err "Download fehlgeschlagen."; exit 1; }
elif command -v wget >/dev/null; then
    wget -q "$url" -O "$work/src.zip" || { c_err "Download fehlgeschlagen."; exit 1; }
else
    c_err "Weder curl noch wget vorhanden."
    exit 1
fi
c_ok "Paket geladen"

unzip -q "$work/src.zip" -d "$work" || { c_err "Entpacken fehlgeschlagen."; exit 1; }
src=$(find "$work" -maxdepth 1 -type d -name 'Kompass-*' | head -1)
[ -d "$src" ] || { c_err "Unerwarteter Paketinhalt."; exit 1; }

# Nur Programmdateien ersetzen. .env, Volumes und alles andere bleiben liegen.
rm -rf ./app
cp -r "$src/app" ./app
for f in Dockerfile docker-compose.yml requirements.txt deploy.sh update.sh \
         README.md .env.example; do
    [ -f "$src/$f" ] && cp "$src/$f" "./$f"
done
chmod +x ./deploy.sh ./update.sh 2>/dev/null
c_ok "Dateien ausgetauscht"

version=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app/version.py 2>/dev/null)
[ -n "$version" ] && c_ok "Neue Version: $version"

case "${1:-}" in
    --no-deploy) c_info "Nicht neu gestartet (--no-deploy)."; exit 0 ;;
esac

if [ -x ./deploy.sh ]; then
    echo
    ./deploy.sh
else
    c_err "deploy.sh fehlt — bitte von Hand starten."
fi
