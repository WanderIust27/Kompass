# KOMPASS — dein lokaler Alltagsassistent

Ein Ort für alles, was im Kopf herumliegt: Aufgaben, Ideen, Haushalt, Käufe,
Notizen, Menschen. Kompass sortiert es ein, plant deinen Tag, bremst dich bei
Ideen und Käufen und redet mit dir über eine KI, die **auf deinem eigenen
Server** läuft. Keine Cloud, kein Abo, keine Konten.

Gebaut für einen Kopf mit ADHS. Das ist keine Marketingzeile, sondern die
Bauanleitung: Es gibt **ein** Eingabefeld statt zehn Formulare, der Tag zeigt
**drei** Dinge statt vierzig, und die Regeln greifen von allein, weil man sich
im richtigen Moment nicht auf seine Selbstdisziplin verlassen kann.

---

## Was drin ist

| Reiter | Was dort passiert |
|---|---|
| **Heute** | Briefing, Tagesplan mit Zeitbudget, fälliger Haushalt, Abend-Check-in, Protokoll dessen, was Kompass selbst umgestellt hat |
| **Inbox** | Alles Reingeworfene. Kompass schlägt die Schublade vor, du bestätigst mit einem Tippen |
| **Aufgaben** | Offenes mit Dauer, Energie, Ort und Fälligkeit — filterbar nach Tagesform |
| **Projekte** | Laufende Projekte mit Platzlimit, dazu der Ideen-Parkplatz mit Karenzzeit und Bewertungsritual |
| **Haushalt** | Routinen, deren Rhythmus ab der letzten Erledigung zählt und sich selbst korrigiert |
| **Käufe** | Warteliste nach Preis, vier unbequeme Fragen, Recherche im Netz, Budget, spätere Nutzungskontrolle |
| **Notizen** | Volltext **und** semantische Suche — findet auch, was du anders formuliert hast |
| **Empfehlungen** | Bücher, Filme, Serien, Podcasts, Spiele: Liste, Bewertung, neue Vorschläge nach deinem Geschmack |
| **Menschen** | Wer dran wäre, Geburtstage, was du dir über jemanden gemerkt hast |
| **Fragen** | Chat mit Kompass — er kennt deinen Stand, kann aber nichts eintragen |
| **Mehr** | Deine Zeit pro Wochentag, alle Regeln, Ton, Modellwahl, was er über dich gelernt hat |

---

## Die vier Regeln

Kompass ist im Kern eine Sammlung von Regeln, die zwischen Impuls und Handlung
Zeit schieben. Alle sind unter **Mehr** einstellbar.

### 1. Ideen kommen auf den Parkplatz

Jede Idee liegt erst **7 Tage** und darf in dieser Zeit nicht gestartet werden.
Danach ist sie *reif* und du beantwortest vier Fragen:

* Woran merkst du, dass es fertig ist?
* Wie viele Stunden kostet das realistisch — mal zwei gerechnet?
* Was bleibt dafür liegen?
* Warum jetzt und nicht in drei Monaten?

Erst dann sagt das Modell, was es davon hält. Die Reihenfolge ist Absicht: Wer
die Fragen beantwortet hat, hat die halbe Entscheidung schon getroffen.

### 2. Höchstens drei Projekte gleichzeitig

Das vierte Projekt lehnt Kompass ab. Nicht mit einem Hinweis, sondern wirklich —
du musst erst eines abschließen oder auf Eis legen. Wenn es trotzdem sein muss,
geht es mit Begründung, und die Begründung steht danach im Protokoll. Das ist
kein Misstrauen, das ist die Erinnerung an dich selbst in vier Wochen.

### 3. Käufe warten, gestaffelt nach Preis

| Preis | Wartezeit |
|---|---|
| unter 20 € | keine |
| ab 20 € | 48 Stunden |
| ab 100 € | 7 Tage |

Während der Wartezeit passiert nichts. Danach kommt das Verhör (welches Problem
löst es *heute*, was benutzt du gerade dafür, was passiert ohne, wo steht es in
drei Monaten), dann erst die Recherche im Netz — Preisspanne, häufigste Kritik,
günstigere oder gebrauchte Alternative.

Wer mit der Recherche anfängt, hat sich meistens schon entschieden und sucht nur
noch Bestätigung. Deshalb steht sie hinten.

**30 Tage nach dem Kauf** fragt Kompass nach: benutzt du das Ding? Aus den
Antworten wird eine Zahl, die er dir beim nächsten Mal vorhält.

### 4. Der Haushalt zählt ab der Erledigung

Eine Routine wird nicht am Dienstag fällig, sondern *sieben Tage nachdem du sie
zuletzt gemacht hast*. Wer eine Woche weg war, kommt sonst zu einem Berg heim,
der täglich weiter wächst.

Und: Wer eine Routine **dreimal hintereinander wegdrückt**, meint nicht sich
selbst, sondern den Rhythmus. Kompass streckt ihn dann um die Hälfte, ganz von
allein, und schreibt es ins Protokoll.

---

## Der Tagesplan

Kompass plant selbst und sagt, was er getan hat — das war die Ansage, und daran
hält er sich nach festen Regeln:

* **Was gestern offen blieb, kommt auf heute.** Kein Datum von vorgestern, das
  einen schon beim Aufwachen anklagt.
* **Tägliche Routinen stehen immer drin, von den selteneren höchstens zwei.**
  Sonst wird aus jedem Dienstag ein Putztag, und man fängt gar nicht erst an.
* **Gefüllt wird nach der Zeit, die du wirklich hast** (Mehr → Deine Zeit), nicht
  nach Wunschdenken. Überfälliges kommt immer rein, auch wenn es sprengt — dann
  sagt das Briefing, dass der Plan zu voll ist, statt es zu verschweigen.
* **Pro Projekt nur der nächste Schritt.** Alles andere wäre Ballast.

Was nicht passt, steht sichtbar als Überlauf darunter. Nicht heimlich im Plan.

---

## Die KI

Kompass benutzt **Ollama**, und zwar standardmäßig das, das ohnehin schon für
[PULS](https://github.com/WanderIust27/Puls) läuft. Bei 8 GB VRAM ist das der
richtige Weg: ein Modell im Speicher statt zwei, die sich gegenseitig
hinauswerfen. Der Code der beiden Anwendungen hat nichts miteinander zu tun —
nur die Adresse des Modells zeigt auf denselben Container.

Durch das Modell laufen:

* das Einsortieren der Inbox,
* Morgenbriefing und Abend-Check-in,
* die Einschätzung von Ideen und Käufen,
* die Zusammenfassung der Kaufrecherche,
* Empfehlungen,
* der Chat.

**Ohne Modell bleibt Kompass vollständig bedienbar.** Die Inbox sortiert dann
nach Stichworten, das Briefing wird gerechnet statt geschrieben, und an jeder
Stelle steht dabei, dass gerade kein Modell erreichbar war. Eine App, die ohne
KI stehenbleibt, taugt im Alltag nichts.

Für die **semantische Notizsuche** kommt ein zweites, winziges Modell dazu
(`nomic-embed-text`, rund 270 MB). Jede Notiz bekommt beim Speichern einen
Vektor; gesucht wird über Volltext *und* Ähnlichkeit, und die Treffer werden
zusammengeführt.

---

## Installation auf Unraid

Unraid bringt kein `docker compose` mit. `deploy.sh` macht dasselbe mit reinen
docker-Befehlen und ist gefahrlos wiederholbar.

```sh
# 1. Holen
cd /mnt/user/appdata
git clone https://github.com/WanderIust27/Kompass.git
cd Kompass

# 2. Einstellungen anlegen (wird bei Updates nie überschrieben)
cp .env.example .env
nano .env

# 3. Starten
./deploy.sh
```

Das Skript legt das Netz `kompass-ki` an, hängt den vorhandenen Container
`puls-ollama` hinein, baut das Image und startet Kompass auf Port **1338**
(PULS liegt auf 1337, die beiden kommen sich nicht in die Quere).

Danach einmalig das kleine Suchmodell holen:

```sh
docker exec puls-ollama ollama pull nomic-embed-text
```

**Läuft kein PULS auf der Kiste?** Dann startet `./deploy.sh --own-ollama` einen
eigenen Ollama-Container mit.

Weitere Befehle:

```sh
./deploy.sh --no-build   # nur neu starten
./deploy.sh logs         # Logs verfolgen
./deploy.sh status       # Kurzüberblick
./deploy.sh stop         # anhalten und entfernen (Daten bleiben)
```

### Auf dem Telefon

Im Browser `http://<server>:1338` öffnen und **Zum Startbildschirm hinzufügen**.
Danach verhält es sich wie eine App — eigenes Fenster, eigenes Symbol, und die
Oberfläche liegt im Cache, wenn das Netz mal hakt.

---

## Der erste Tag

1. **Mehr → Deine Zeit**: Wie viele Minuten hast du montags wirklich? Lieber zu
   wenig eintragen als zu viel. 45 ehrliche Minuten schlagen 120 erfundene.
2. **Haushalt**: Der Startplan mit 20 Routinen ist schon da, zeitlich versetzt,
   damit am ersten Tag keine Wand vor dir steht. Alles, was du nicht machst,
   löschen — eine Liste, die lügt, liest man nach drei Tagen nicht mehr.
3. **Mehr → Regeln**: Karenzzeit, Projektlimit, Kaufschwellen und Monatsbudget
   auf deine Zahlen stellen.
4. Dann einfach **alles reinwerfen**, was dir einfällt. Einsortiert wird später.

---

## Was nach draußen geht

Mit `ALLOW_WEB=1` (Standard) darf Kompass für die Kaufrecherche und für Buch-
und Filmdaten ins Netz. Hinaus geht dabei **nur ein Suchbegriff** — der Name des
Produkts oder des Titels. Niemals Aufgaben, Notizen, Ideen, Namen oder
irgendetwas anderes aus deiner Datenbank.

Mit `ALLOW_WEB=0` ist damit Schluss. Dann berät Kompass rein aus deinen eigenen
Antworten und dem Wissen des Modells, und die Recherche-Knöpfe sagen offen, dass
sie abgeschaltet sind.

Gesucht wird über DuckDuckGo. Wer eine eigene **SearXNG**-Instanz betreibt, trägt
sie als `SEARXNG_URL` ein — dann läuft auch der Suchbegriff über den eigenen
Server. Buchdaten kommen von OpenLibrary (ohne Schlüssel), Film- und Seriendaten
von TMDB, falls ein `TMDB_API_KEY` hinterlegt ist.

---

## Einstellungen

Alles in der `.env`:

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `KOMPASS_PORT` | 1338 | Port der Oberfläche |
| `TZ` | Europe/Berlin | Zeitzone (wichtig für Briefing-Zeiten) |
| `OLLAMA_URL` | `http://puls-ollama:11434` | Wo das Modell läuft |
| `OLLAMA_MODEL` | qwen3:8b | Hauptmodell |
| `EMBED_MODEL` | nomic-embed-text | Für die semantische Suche; leer = aus |
| `KOMPASS_TOKEN` | leer | Leer = offen im Heimnetz. Gesetzt = jede Anfrage braucht den Token |
| `ALLOW_WEB` | 1 | Internetzugriff für Recherche |
| `SEARXNG_URL` | leer | Eigene Suchinstanz statt DuckDuckGo |
| `TMDB_API_KEY` | leer | Für Film- und Seriendaten |

In der Oberfläche unter **Mehr** zusätzlich: Zeitbudget pro Wochentag, Karenzzeit,
Projektlimit, Kaufschwellen und -wartezeiten, Monatsbudget, Nutzungskontrolle,
Briefing-Uhrzeiten, Tonfall, Modellwahl.

---

## Sicherung

Alles liegt im Docker-Volume `kompass-data` in einer einzigen SQLite-Datei.

```sh
# Sichern
docker run --rm -v kompass-data:/data -v /mnt/user/backups:/out alpine \
    tar czf /out/kompass-$(date +%F).tar.gz -C /data .

# Zurückspielen
docker run --rm -v kompass-data:/data -v /mnt/user/backups:/in alpine \
    tar xzf /in/kompass-2026-09-11.tar.gz -C /data
```

Ein Update rührt das Volume nie an.

---

## Aktualisieren

```sh
./update.sh
```

Holt den neuen Stand von GitHub, tauscht die Programmdateien aus und startet neu.
Deine `.env` und das Datenvolume bleiben unberührt. Mit `--no-deploy` werden nur
die Dateien ersetzt.

---

## Wenn etwas klemmt

**„kein Modell" steht oben rechts.**
Der Ollama-Container ist nicht erreichbar. Prüfen:

```sh
docker ps | grep ollama
docker network inspect kompass-ki --format '{{range .Containers}}{{.Name}} {{end}}'
```

Steht der Ollama-Container nicht in der zweiten Ausgabe, hängt er nicht im
gemeinsamen Netz. `./deploy.sh` nochmal laufen lassen, das erledigt es.

**Antworten dauern ewig.**
Wahrscheinlich rechnet Ollama auf der CPU. In der PULS-`.env` `OLLAMA_GPU=all`
und `OLLAMA_RUNTIME=nvidia` setzen und den Ollama-Container neu starten.

**Die Notizsuche findet nur Wörter, keinen Sinn.**
Das Einbettungsmodell fehlt: `docker exec puls-ollama ollama pull nomic-embed-text`.
Bestehende Notizen holt Kompass stündlich von allein nach.

**Kaufrecherche liefert nichts.**
Entweder ist `ALLOW_WEB=0`, oder DuckDuckGo mag den Server gerade nicht. Eine
eigene SearXNG-Instanz über `SEARXNG_URL` ist der stabilere Weg.

---

## Aufbau

```
app/
  main.py              FastAPI, Fehlerübersetzung, statische Dateien
  config.py            alles über Umgebungsvariablen
  db.py                Schema, Startdaten, Zugriff (SQLite, kein ORM)
  routers/api.py       die HTTP-Schnittstelle
  services/
    triage.py          Inbox einsortieren (mit Stichwort-Notnagel ohne Modell)
    tasks.py           Aufgaben
    routines.py        Haushalt samt Rhythmus-Korrektur
    projects.py        Ideen-Parkplatz, Ritual, Projektlimit
    purchases.py       Wartefrist, Verhör, Recherche, Budget, Nutzungskontrolle
    notes.py           Volltext + Vektoren
    people.py          Menschen
    recommendations.py Empfehlungen
    planner.py         Tagesplan
    briefing.py        Morgen und Abend
    profile.py         was er über dich gelernt hat (gerechnet, nicht geraten)
    chat.py            Gespräch
    websearch.py       DuckDuckGo/SearXNG, OpenLibrary, TMDB
    ollama_client.py   Modell und Einbettungen
    scheduler.py       Hintergrundarbeit
  static/              Oberfläche (Vanilla JS, keine Abhängigkeiten)
tests/                 python3 tests/run_all.sh
```

Keine Bibliothek mehr als nötig: FastAPI, httpx, APScheduler. Kein Frontend-Build,
kein npm, keine Migrationsschicht. Das Ganze soll in fünf Jahren noch starten.

---

## Tests

```sh
sh tests/run_all.sh
```

Drei Stück, keiner fasst echte Daten an:

* **test_rules.py** — die Regeln, die weh tun, wenn sie falsch sind: Wartefristen,
  Karenzzeit, Projektlimit, Haushaltsrhythmus, Tagesplan, Inbox ohne Modell.
* **test_api.py** — jeder Endpunkt gegen eine Wegwerf-Datenbank, mit totem Ollama
  und ohne Internet. Kompass muss auch dann vollständig antworten.
* **test_frontend.py** — Oberfläche und Skript passen zusammen: keine getippte
  ID, kein Reiter ohne Ladefunktion, kein Aufruf auf einen Endpunkt, den es nicht gibt.
