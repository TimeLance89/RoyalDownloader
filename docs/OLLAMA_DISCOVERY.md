# Optionale lokale KI-Discovery

RoyalDownloader kann den bestehenden Startseiten-Katalog optional durch
Ollama kuratieren lassen. Die Funktion ergänzt Discovery und hat keinen Zugriff
auf Provider-Auswahl, Queue, Dateiverwaltung oder Download-Entscheidungen.

## Einrichtung

Unter **Einstellungen → Externe Dienste → Royal KI · Ollama**:

1. „Intelligente Discovery aktivieren“ einschalten.
2. Ollama-Adresse eintragen, etwa `http://192.168.1.20:11434` oder im selben
   Compose-Netz `http://ollama:11434`.
3. Ein lokal installiertes Modell wählen und die Verbindung testen.
4. Das Zeitlimit passend zur NAS-Leistung wählen (Standard: 180 Sekunden).
5. Einstellungen speichern.

Alternativ stehen `OLLAMA_ENABLED`, `OLLAMA_URL`, `OLLAMA_MODEL` und
`OLLAMA_TIMEOUT_SECONDS` als Container-Umgebungsvariablen bereit.

Erst beim Laden eines vorhandenen Royal-Katalogs sendet Royal bis zu 24
Kandidaten mit Titel, Typ, Jahr, Bewertung, Genres und gekürzter Beschreibung
sowie ein kompaktes Geschmacksprofil an Ollama. Die Antwort wird sechs Stunden
im Arbeitsspeicher zwischengespeichert. Es werden keine Dateien, Zugangsdaten,
Suchprotokolle, Provider-Entscheidungen oder Queue-Daten übertragen.

Ist Ollama aktiviert, zeigt die Startseite Aufbau, Erfolg oder einen konkreten
Fehlerzustand mit Wiederholen-Aktion. Alle klassischen Empfehlungen und
sämtliche Downloader-Funktionen laufen unabhängig davon unverändert weiter.
