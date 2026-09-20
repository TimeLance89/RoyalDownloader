# Royal Intelligence

Royal Intelligence kuratiert ausschließlich bereits vorhandene Startseiten-Kandidaten. Es startet keine Downloads, verändert weder Queue noch Provider, Dateien, Storage oder Automation.

## Modul und Provider

Das Modul **Royal Intelligence** wird im Module Manager aktiviert. Ist es deaktiviert, werden keinerlei Provider-Anfragen ausgeführt und die Startseite verwendet unverändert ihr klassisches Ranking. Bestehende aktivierte Ollama-Konfigurationen werden bei der Migration übernommen.

Verfügbare Provider sind **JEV** und **Ollama**. JEV verwendet TypeSafe System One mit den getypten Primitives `score` und `choice`: pro Kandidat entsteht ein normalisierter Recommendation Score (0–100) und ein `taste`-, `adjacent`- oder `surprise`-Winkel. Das ist keine Wahrscheinlichkeit. RoyalDownloader trifft danach die endgültige, genrediversifizierte Auswahl selbst und erzeugt Gründe aus realen Genreüberschneidungen.

## Daten und Datenschutz

JEV erhält nur bis zu 24 bestehende Kandidaten mit Titel, Typ, Jahr, Rating, Genres und kurzer Beschreibung sowie ein kompaktes Geschmacksprofil (gewichtete Vorlieben, Interaktionen, Confidence). Nicht übertragen werden API-Keys, Benutzername, Historie, Pfade, Queue-, Download-, Provider- oder Logdaten. Bei Ollama bleibt dieselbe begrenzte Nutzlast lokal.

Der JEV-Key wird ausschließlich gespeichert und niemals von der Konfigurations-API zurückgegeben oder geloggt. Die Verbindungstaste sendet nur einen synthetischen, getypten Probe-State.

## Cache und Fehler

Ergebnisse werden sechs Stunden im Speicher gecacht; Provider, Modell, Profil und Kandidatenmenge bilden den Schlüssel. Bei Timeout, Rate Limit, Auth- oder Antwortfehler wird nur der Intelligence-Bereich ausgelassen; die Startseite und alle Core-Funktionen bleiben verfügbar. Ein valider Cache wird bevorzugt verwendet. Es gibt keinen stillen Wechsel zu einem Cloud-Provider.

Die JEV-Payload entspricht der offiziellen TypeSafe System-One API: `POST /v1/systemone` mit `state`, `model: jev-latest` und `questions`. Ein echter Live-Test benötigt einen eigenen API-Key.
