# Zu Royal Downloader beitragen

Danke für dein Interesse. Änderungen sollen den selbst gehosteten Betrieb
stabiler, nachvollziehbarer oder einfacher machen.

## Vor einer Änderung

- Für Fehler das GitHub-Formular **Bug melden** verwenden.
- Größere Funktionen zuerst als Feature-Idee beschreiben.
- Keine Zugangsdaten, API-Keys, Cookies, privaten Medienpfade oder vollständige
  Konfigurationsdateien veröffentlichen.
- Änderungen an Download-, Update- und Duplikatschutzlogik müssen ausfallsicher
  sein: Bei unklarem Zustand darf kein doppelter oder falscher Download starten.

## Lokale Einrichtung

```bash
git clone https://github.com/TimeLance89/SerienDownloader.git RoyalDownloader
cd RoyalDownloader
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Für den vollständigen Laufzeitstack wird Docker Compose empfohlen:

```bash
cp .env.example .env
docker compose up -d --build
```

## Mindestprüfungen

Vor einem Pull Request mindestens ausführen:

```bash
python -m py_compile *.py
docker compose config
node --check web/app.js
```

Die vollständige Regression wird intern vor einem Release ausgeführt.

## Pull Requests

- Ein Thema pro Pull Request.
- Titel kurz und im Imperativ formulieren.
- Ursache, Änderung und Auswirkung im Beschreibungstext nennen.
- UI-Änderungen mit einem Screenshot dokumentieren.
- Neue Konfigurationswerte in `.env.example` und `DOCKER.md` ergänzen.
- Persistente Daten und bestehende `settings.ini` müssen kompatibel bleiben.

## Stil

- Python: bestehende Typen, Locks und Fehlerpfade respektieren.
- JavaScript: keine Framework-Abhängigkeit ohne vorherige Abstimmung.
- UI: bestehende Dark-/Gold-Gestaltung und mobile Darstellung beibehalten.
- Dokumentation: Deutsch, kurze Abschnitte, ausführbare Beispiele.

