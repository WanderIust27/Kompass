#!/bin/sh
# Alle Tests der Reihe nach. Keine davon fasst echte Daten an — jeder legt
# sich eine Wegwerf-Datenbank in /tmp an.
#
#   sh tests/run_all.sh
cd "$(dirname "$0")/.." || exit 1

status=0
for t in tests/test_rules.py tests/test_api.py tests/test_frontend.py; do
    echo
    echo "=============================================================="
    echo "  $t"
    echo "=============================================================="
    python3 "$t" 2>&1 | grep -v "^20[0-9][0-9]-" || status=1
done

echo
if [ "$status" = "0" ]; then
    printf '\033[32m✓\033[0m Alles gruen.\n'
else
    printf '\033[31m✗\033[0m Mindestens ein Test ist gefallen.\n'
fi
exit $status
