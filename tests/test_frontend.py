"""Prueft, dass Oberfläche und Skript zusammenpassen.

Eine getippte ID fällt im Browser sonst erst auf, wenn man den Reiter
oeffnet — und dann bleibt er stumm. Dieser Test zieht solche Fehler vor.

Aufruf:  python3 tests/test_frontend.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
css = (ROOT / "app/static/style.css").read_text(encoding="utf-8")

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


html_ids = set(re.findall(r'id="([^"]+)"', html))
js_ids = set(re.findall(r'\$\("#([A-Za-z][\w-]*)"\)', js))
# Zur Laufzeit erzeugte Elemente muessen nicht im HTML stehen.
runtime_ids = {"pending", "briefAgain", "replanBtn"}

missing = sorted(js_ids - html_ids - runtime_ids)
check("jede vom Skript gesuchte ID gibt es im HTML", missing, [])

views = set(re.findall(r'data-view="(\w+)"', html))
sections = set(re.findall(r'id="view-(\w+)"', html))
check("zu jedem Reiter gehört eine Ansicht", sorted(views - sections), [])
check("keine Ansicht ohne Reiter", sorted(sections - views), [])

loaders = set(re.findall(r'LOADERS\.(\w+)\s*=', js))
check("jeder Reiter hat eine Ladefunktion", sorted(views - loaders), [])

# Klassen, die das Skript vergibt, muessen im Stylesheet auch etwas bewirken.
for klass in ["row", "check", "btn", "link", "take", "msg", "empty", "toast",
              "list", "meta", "grow", "acts", "hub", "crumb", "label", "quiet",
              "foot", "block", "when", "gone", "briefing", "scale", "cap-grid",
              "adder", "fields", "chat", "state", "dot", "capture"]:
    if f".{klass}" not in css:
        failures.append(f"Klasse .{klass} fehlt im Stylesheet")
        print(f"FAIL Klasse .{klass} wird benutzt, ist aber nicht gestaltet")
print(f"OK   alle benutzten Klassen sind gestaltet"
      if not any("Klasse" in f for f in failures) else "")

# Die Endpunkte, die das Skript ruft, muss es im Router geben.
api_py = (ROOT / "app/routers/api.py").read_text(encoding="utf-8")
routes = set(re.findall(r'@router\.\w+\("([^"]+)"', api_py))
route_shapes = {re.sub(r"\{[^}]+\}", "*", r) for r in routes}
called = set()
for raw in re.findall(r'api\(\s*[`"]([^`"]+)[`"]', js):
    path = raw.split("?")[0]
    path = re.sub(r"\$\{[^}]+\}", "*", path).rstrip("/")
    called.add(path or "/")
unknown = sorted(p for p in called if p not in route_shapes)
check("jeder gerufene Endpunkt existiert", unknown, [])

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen.")
    sys.exit(1)
print("Oberfläche und Skript passen zusammen.")
