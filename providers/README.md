# Anbieteradapter

Jeder Kataloganbieter besitzt genau ein Modul in diesem Verzeichnis. Gemeinsame
Such-, Film-, Serien-, Episoden- und Hoster-Datenmodelle liegen in `models.py`.

## Aufbau

| Modul | Anbieter |
|---|---|
| `filmfrei24.py` | FilmFrei24 |
| `filmpalast.py` | Filmpalast |
| `megakino.py` | MegaKino |
| `moflix.py` | Moflix |
| `einschalten.py` | Einschalten |
| `kinox.py` | Kinox |
| `kinoger.py` | KinoGer |
| `xcine.py` | XCine |
| `sflix.py` | SFlix (Englisch) |
| `serienstream.py` | Serienstream |

Neue Adapter werden zusätzlich in den Provider-Tabellen in `server.py` und in
`providers/catalog.py` registriert. Dort sind Medienarten, Standardsprache,
Erkennungsmerkmale und Standardprioritäten hinterlegt. Anbieter dürfen keine
eigenen inkompatiblen Ergebnisobjekte einführen; sie verwenden die Typen aus
`providers.models`.

`content_language` verwendet einen kurzen BCP-47-Sprachcode wie `de` oder `en`.
Er beschreibt die erwartete Inhaltssprache des Anbieters. Meldet ein einzelner
Hoster eine konkrete Sprache, hat diese beim Download Vorrang.
