# Repository auf `RoyalDownloader` umbenennen

[← Zur Projektübersicht](../README.md)

Der sichtbare Produktname lautet **Royal Downloader**. GitHub-Repository-Namen
können keine Leerzeichen enthalten; als technischer Slug wird deshalb
`RoyalDownloader` empfohlen.

## Ziel

| Element | Vorher | Nachher |
|---|---|---|
| Produktname | SerienDownloader | Royal Downloader |
| Repository | `TimeLance89/SerienDownloader` | `TimeLance89/RoyalDownloader` |
| Clone-Link | `https://github.com/TimeLance89/SerienDownloader.git` | `https://github.com/TimeLance89/RoyalDownloader.git` |

## 1. Vorbereiten

Vor der Umbenennung sicherstellen, dass `main` vollständig gepusht ist:

```bash
git status
git fetch origin
git rev-list --left-right --count main...origin/main
```

Erwartet werden ein sauberer Arbeitsbaum und `0  0` beim Branchvergleich.

## 2. Repository auf GitHub umbenennen

1. Repository auf GitHub öffnen.
2. **Settings → General → Repository name** wählen.
3. `RoyalDownloader` eintragen.
4. **Rename** bestätigen.

GitHub richtet Weiterleitungen für alte Web-, Clone- und API-URLs ein. Diese
Weiterleitung sollte nur als Übergang dienen. Unter dem alten Namen darf später
kein neues Repository angelegt werden, weil dadurch Weiterleitungen ungültig
werden können.

## 3. Lokales Git-Remote aktualisieren

```bash
git remote set-url origin https://github.com/TimeLance89/RoyalDownloader.git
git remote -v
git fetch origin
```

Bei GitHub CLI zusätzlich prüfen:

```bash
gh repo view TimeLance89/RoyalDownloader
```

## 4. Updater und Dokumentation umstellen

Nach erfolgreicher GitHub-Umbenennung alle fest hinterlegten Repository-Werte
von `TimeLance89/SerienDownloader` auf `TimeLance89/RoyalDownloader` ändern.
Betroffen sind derzeit insbesondere:

- `server.py`
- `update_checker.py`
- `docker-compose.yml`
- `.env.example`
- `DOCKER.md`
- `web/index.html`
- `README.md` und `CONTRIBUTING.md`

Fundstellen kontrollieren:

```bash
rg -n "TimeLance89/SerienDownloader|github.com/TimeLance89/SerienDownloader"
```

In einer vorhandenen NAS-Installation außerdem `.env` anpassen:

```dotenv
UPDATE_GITHUB_REPOSITORY=TimeLance89/RoyalDownloader
UPDATE_GITHUB_BRANCH=main
```

Danach den Container neu erstellen:

```bash
docker compose up -d --build
docker compose logs -f seriendownloader
```

## 5. GitHub-Auftritt aktualisieren

Empfohlene Beschreibung:

> Self-hosted media automation for Jellyfin, Telegram and Seerr — optimized for Docker and NAS.

Empfohlene Topics:

```text
self-hosted  jellyfin  docker  nas  telegram-bot
fastapi  python  media-automation  seerr
```

Optional danach unter **Settings → General** folgende Funktionen aktivieren:

- Issues
- Private vulnerability reporting
- Discussions, falls Supportfragen getrennt von Fehlern geführt werden sollen

## 6. Abschluss prüfen

- Neue Repository-URL öffnet ohne Weiterleitung.
- `git push origin main` funktioniert.
- Der Updater zeigt `TimeLance89/RoyalDownloader · main` als erreichbar.
- Eine Updateprüfung liefert die aktuelle `main`-Revision.
- README, Issue-Formulare und Dokumentationslinks funktionieren.
- Docker startet mit vorhandenen `data`- und `runtime`-Ordnern unverändert.

Die internen Namen `FilmeDownloader` für den persistenten Konfigurationsordner
und `seriendownloader` für den Compose-Service sollten zunächst bestehen bleiben.
Eine Änderung würde Migrationen für vorhandene NAS-Installationen erfordern und
ist für das öffentliche Branding nicht notwendig.
