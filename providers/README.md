# Anbieteradapter

Jeder Kataloganbieter besitzt genau ein Modul in diesem Verzeichnis. Gemeinsame
Such-, Film-, Serien-, Episoden- und Hoster-Datenmodelle liegen in `models.py`.

## Aufbau

| Modul | Anbieter |
|---|---|
| `filmpalast.py` | Filmpalast |
| `megakino.py` | MegaKino |
| `moflix.py` | Moflix |
| `einschalten.py` | Einschalten |
| `kinox.py` | Kinox |
| `kinoger.py` | KinoGer |
| `xcine.py` | XCine |
| `serienstream.py` | Serienstream |

Neue Adapter werden zusätzlich in den Provider-Tabellen in `server.py` und in
den Standardprioritäten in `config.py` registriert. Anbieter dürfen keine
eigenen inkompatiblen Ergebnisobjekte einführen; sie verwenden die Typen aus
`providers.models`.
