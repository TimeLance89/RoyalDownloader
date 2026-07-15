# Migration auf `RoyalDownloader`

[← Zur Projektübersicht](../README.md)

Das Repository wurde am 15. Juli 2026 von `TimeLance89/SerienDownloader` in
`TimeLance89/RoyalDownloader` umbenannt. Der sichtbare Produktname lautet
**Royal Downloader**; der technische GitHub-Slug enthält keine Leerzeichen.

## Ziel

| Element | Vorher | Nachher |
|---|---|---|
| Produktname | SerienDownloader | Royal Downloader |
| Repository | `TimeLance89/SerienDownloader` | `TimeLance89/RoyalDownloader` |
| Clone-Link | `https://github.com/TimeLance89/SerienDownloader.git` | `https://github.com/TimeLance89/RoyalDownloader.git` |

## 1. Lokales Git-Remote aktualisieren

```bash
git remote set-url origin https://github.com/TimeLance89/RoyalDownloader.git
git remote -v
git fetch origin
```

Bei GitHub CLI zusätzlich prüfen:

```bash
gh repo view TimeLance89/RoyalDownloader
```

GitHub leitet alte Web- und Clone-URLs derzeit weiter. Das Remote sollte
trotzdem aktualisiert werden, damit die Installation nicht dauerhaft von der
Weiterleitung abhängt.

## 2. Updater einer vorhandenen Installation umstellen

In der `.env` auf dem NAS den Repository-Wert anpassen:

```dotenv
UPDATE_GITHUB_REPOSITORY=TimeLance89/RoyalDownloader
UPDATE_GITHUB_BRANCH=main
```

Danach den Container neu erstellen, damit die Umgebung neu eingelesen wird:

```bash
docker compose up -d --build
docker compose logs -f seriendownloader
```

Ohne eigenen `UPDATE_GITHUB_REPOSITORY`-Eintrag verwendet ein aktueller Build
automatisch `TimeLance89/RoyalDownloader`.

## 3. Externe Verweise aktualisieren

Lesezeichen, API-Integrationen, Deployment-Skripte und eigene Dokumentation auf
folgende Adressen umstellen:

```text
https://github.com/TimeLance89/RoyalDownloader
https://github.com/TimeLance89/RoyalDownloader.git
```

Unter dem alten Namen sollte kein neues Repository angelegt werden, weil dies
GitHubs Weiterleitung ungültig machen kann.

## 4. Abschluss prüfen

- Die neue Repository-URL öffnet ohne Weiterleitung.
- `git push origin main` funktioniert.
- Der Updater zeigt `TimeLance89/RoyalDownloader · main` als erreichbar.
- Eine Updateprüfung liefert die aktuelle `main`-Revision.
- README, Issue-Formulare und Dokumentationslinks funktionieren.
- Docker startet mit vorhandenen `data`- und `runtime`-Ordnern unverändert.

Die internen Namen `FilmeDownloader` für den persistenten Konfigurationsordner
und `seriendownloader` für den Compose-Service bleiben aus Gründen der
Abwärtskompatibilität bestehen. Ihre Umbenennung würde vorhandene NAS-Volumes
und Startskripte unnötig brechen.
