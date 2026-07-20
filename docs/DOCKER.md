# Docker and NAS operation (24/7)

[← Project overview](../README.md) ·
[Jellyfin recommendations](JELLYFIN_RECOMMENDER.md) ·
[Repository migration](REPOSITORY_RENAME.md)

## Contents

- [Moonfin and Seerr](#moonfin-and-seerr-fire-tv)
- [Deployment A: mounted source folder](#deployment-a-mounted-source-folder-with-startsh)
- [Deployment B: Docker Compose](#deployment-b-docker-compose)
- [Volumes and persistent data](#volumes-and-persistent-data)
- [Environment variables](#environment-variables)
- [DNS and provider blocking](#dns-and-provider-blocking)
- [Jellyfin and automation](#jellyfin-and-247-automation)
- [Interface language](#interface-language)
- [Provider catalog](#provider-catalog)
- [Updates](#updates)
- [Telegram requests](#telegram-requests)

## Moonfin and Seerr (Fire TV)

Royal Downloader can use a real Seerr container for requests created in Moonfin:

```text
Moonfin (Fire TV) → Seerr → Royal Downloader → /movies or /serien → Jellyfin
```

Seerr provides the request catalog and approval workflow; it is not a download
provider. Royal Downloader polls approved requests, downloads missing media,
and starts a Jellyfin library scan. Radarr and Sonarr are not required for this
route.

4K requests are marked unsupported unless a provider offers a guaranteed 4K
selection. They are never silently downloaded as a normal release.

### Initial NAS setup

1. Copy the repository to the NAS and copy `.env.example` to `.env`.
2. Set `MOVIES_HOST_DIR` and `SERIES_HOST_DIR` to the actual Jellyfin media
   directories. Royal Downloader and Jellyfin must see the same host folders.
   For access from other devices set `BIND_ADDRESS=0.0.0.0`,
   `SEERR_BIND_ADDRESS=0.0.0.0`, and `APP_USERNAME`/`APP_PASSWORD` – both
   ports stay host-local otherwise.
3. Prepare the Seerr data directory:

   ```bash
   mkdir -p data/seerr
   sudo chown -R 1000:1000 data/seerr
   docker compose up -d --build
   ```

4. Open `http://<NAS-IP>:5055` and complete the Seerr wizard with Jellyfin.
   Skip Radarr and Sonarr.
5. Copy the API key from **Seerr → Settings → General**.
6. Open **Royal Downloader → Settings → Seerr**, enter
   `http://<NAS-IP>:5055` and the API key, enable the integration, and save.
   Royal Downloader configures the Moonfin plugin and Fire TV user profile.
7. Enable automatic movie and series approval for the Fire TV user in Seerr.
8. Open Moonfin on Fire TV and sign in to its Seerr area once with the normal
   Jellyfin credentials.

### Moving an existing installation

- Stop the old containers first. Never copy Seerr's SQLite files while Seerr is
  running.
- Copy the complete `data/` directory. It contains settings, queue state,
  cookies, subscriptions, Seerr data, and credentials.
- Copy movie and series files separately to the media folders configured in
  `.env`.
- Do not migrate `.downloading` files or the `debug/` directory.
- `data/FilmeDownloader/download_queue.json` resumes automatically on startup.
  Drain the queue before moving if no download should start immediately.

The Docker build context excludes `data/`, `.env`, and downloads, so credentials
do not become part of the image.

Both deployment methods include:

- **Chromium** for browser-assisted extraction and anti-bot sessions;
- **ffmpeg** for HLS/M3U8 processing through yt-dlp.

## Deployment A: mounted source folder with `start.sh`

This mode is useful on NAS platforms that create containers through a graphical
interface and mount a project directory into a generic Python container.
`start.sh` installs runtime dependencies and starts the server.

1. Copy the repository to the NAS, for example `/Deluxe`.
2. Create a container from a Python image such as `python:3.12`.
3. Mount the repository so it is available as `/Deluxe` inside the container.
4. Set the command to:

   ```text
   bash /Deluxe/start.sh
   ```

5. Publish port `8765`.

The script creates persistent `data/` and `downloads/` directories inside the
mounted folder. On first access, the onboarding wizard asks for interface and
content languages, providers, media paths, Jellyfin, TMDB, automation, and
Telegram. It then creates:

```text
data/FilmeDownloader/settings.ini
```

Catalog warm-up and subscription automation remain disabled until this file
exists.

> [!IMPORTANT]
> Use `bash /Deluxe/start.sh`, not only `/Deluxe/start.sh`; this avoids executable
> bit issues on NAS filesystems. The bootstrap container must run as `root`
> because it installs operating-system packages and configures Chromium.

## Deployment B: Docker Compose

Docker Compose creates a self-contained image with dependencies installed during
the image build:

```bash
cp .env.example .env
docker compose up -d --build
```

Open `http://127.0.0.1:8765` on the Docker host. Both web interfaces bind to
`127.0.0.1` by default. For LAN access set `BIND_ADDRESS=0.0.0.0` together
with `APP_USERNAME`/`APP_PASSWORD` in `.env` – with network exposure and no
credentials the container refuses to start. The same applies to Seerr via
`SEERR_BIND_ADDRESS`.

## Volumes and persistent data

| Container path | Purpose |
|---|---|
| `/runtime` | Persistent application revision used by in-app updates (`./runtime` in Compose) |
| `/app/data` or mounted `…/data` | Settings, subscriptions, queue, provider cookies, hoster intelligence, and Seerr request state |
| `/movies` | Movie destination mounted to the Jellyfin movie directory |
| `/serien` | Series destination mounted to the Jellyfin series directory |
| `/app/config` | Persistent Seerr database and configuration |

Deployment A stores data directly in the mounted project directory. Deployment B
uses bind mounts defined in `docker-compose.yml`.

## Environment variables

All variables are optional and have operational defaults.

### Runtime, storage, and networking

| Variable | Default | Purpose |
|---|---|---|
| `SERIENDL_DATA_DIR` | `<project>/data` | Persistent application state |
| `DOWNLOAD_DIR` | `<project>/downloads` | Movie download destination |
| `SERIES_DIR` | `DOWNLOAD_DIR` | Separate series destination; when omitted, series use the movie directory |
| `MOVIES_HOST_DIR` | `./downloads/Filme` | Compose-only NAS movie directory mounted to `/movies` |
| `SERIES_HOST_DIR` | `./downloads/Serien` | Compose-only NAS series directory mounted to `/serien` |
| `HOST` / `PORT` | `0.0.0.0` / `8765` | Server bind address and port inside the container |
| `BIND_ADDRESS` | `127.0.0.1` | Compose-only host interface for port 8765; `0.0.0.0` publishes to the LAN |
| `SEERR_BIND_ADDRESS` | `127.0.0.1` | Compose-only host interface for the Seerr port 5055 |
| `OPEN_BROWSER` | `0` | Prevents opening a desktop browser inside the container |
| `APP_USERNAME` | empty | HTTP Basic Auth username; required for network exposure |
| `APP_PASSWORD` | empty | HTTP Basic Auth password; required for network exposure |
| `ALLOW_UNAUTHENTICATED_LAN` | empty | Deliberate opt-out: `1` allows network exposure without login (not recommended) |
| `DNS_PRIMARY` | `1.1.1.1` | Preferred container resolver |
| `DNS_SECONDARY` | `9.9.9.9` | Fallback container resolver |
| `DNS_OVERRIDE` | `1` | `start.sh` only: set to `0` to keep Docker's existing `resolv.conf` |
| `HLS_CONCURRENT_FRAGMENTS` | `4` | Parallel HLS/DASH fragments |
| `MP4_HTTP_CHUNK_SIZE` | `4M` | HTTP range size used against throttled long-running MP4 connections |
| `SLOW_DOWNLOAD_MIN_KIBPS` | `384` | Minimum sustained speed before switching source; `0` disables the check |
| `SLOW_DOWNLOAD_GRACE_SECONDS` | `45` | Grace period before slow-source detection starts |
| `SLOW_DOWNLOAD_WINDOW_SECONDS` | `90` | Time the speed must remain below the threshold |

### Seerr

| Variable | Default | Purpose |
|---|---|---|
| `SEERR_URL` | `http://seerr:5055` | Internal Seerr address |
| `SEERR_API_KEY` | empty | Seerr API key; can also be stored through the UI |
| `SEERR_ENABLED` | `false` | Enables the approved-request bridge |
| `SEERR_POLL_INTERVAL_SECONDS` | `60` | Seerr polling interval |

### Updates

| Variable | Default | Purpose |
|---|---|---|
| `APP_COMMIT_SHA` | empty | Optional CI revision override; normal builds detect Git automatically |
| `UPDATE_GITHUB_REPOSITORY` | `TimeLance89/RoyalDownloader` | Repository used by the updater |
| `UPDATE_GITHUB_BRANCH` | `main` | Branch compared by the updater |
| `UPDATE_ALLOW_CUSTOM_REPOSITORY` | empty | Must be `1` before a deviating repository or branch takes effect; otherwise the official source stays active |
| `UPDATE_MODE` | `manual` | `manual` or `automatic`; a value saved in the UI takes precedence |
| `AUTO_UPDATE_INTERVAL_HOURS` | `6` | Automatic application update interval, limited to 1–168 hours |
| `YTDLP_AUTO_UPDATE` | `true` | Enables queue-safe stable yt-dlp updates |
| `YTDLP_UPDATE_INTERVAL_HOURS` | `24` | Stable yt-dlp update interval, limited to 1–168 hours |
| `YTDLP_UPDATE_START_DELAY_SECONDS` | `300` | Delay before the first yt-dlp check; minimum 30 seconds |

## DNS and provider blocking

`docker-compose.yml` configures resolvers through Docker's official `dns`
setting. In mounted-folder deployments, `start.sh` writes the same resolvers to
`/etc/resolv.conf` before network access and performs a diagnostic lookup.

DNS-over-TLS is not established directly between Royal Downloader and
`DNS_PRIMARY`. If encrypted upstream DNS is required, run a local resolver that
accepts normal LAN DNS requests and forwards them through DNS-over-TLS.

## Jellyfin and 24/7 automation

All values can be saved through the web UI. Environment variables are useful as
defaults for a fresh installation.

| Variable | Example | Purpose |
|---|---|---|
| `JELLYFIN_URL` | `http://192.168.1.10:8096` | Jellyfin server used for matching and scans |
| `JELLYFIN_API_KEY` | `21ead1…` | Jellyfin API key |
| `JELLYFIN_USER_ID` | `abc123…` | User whose watched state drives subscription rules |
| `JELLYFIN_USER_NAME` | `Alex` | Display name for the selected user |
| `TMDB_API_KEY` | `abc123…` | TMDB v3 API key or API read access token |
| `TMDB_LANGUAGE` | `de-DE` | TMDB metadata language |
| `UI_LANGUAGE` | `en` | Interface language: `de`, `en`, `es`, `fr`, `it`, `nl`, `pl`, `pt`, `tr`, or `uk` |
| `UI_TRANSLATOR_URL` | `http://libretranslate:5000` | Optional self-hosted LibreTranslate base URL |
| `UI_TRANSLATOR_API_KEY` | `secret` | Optional LibreTranslate API key |
| `SFLIX_BASE_URL` | `https://sflix.win` | Replaceable SFlix mirror domain |
| `RIDOMOVIES_BASE_URL` | `https://ridomovies.su` | Replaceable Ridomovies mirror domain |
| `AUTO_DOWNLOAD` | `true` | Automatically download new subscription matches |
| `CHECK_INTERVAL_MIN` | `30` | Subscription check interval; minimum 5 minutes |
| `DL_WINDOW_START` | `1` | First allowed automatic-download hour, 0–23 |
| `DL_WINDOW_END` | `7` | Last allowed hour; a start greater than end crosses midnight |
| `TELEGRAM_ENABLED` | `true` | Enables Telegram requests |
| `TELEGRAM_BOT_TOKEN` | `123…:AA…` | Token created by `@BotFather` |
| `TELEGRAM_CHAT_ID` | `123456789` | Only chat allowed to trigger downloads |

A value saved through the UI takes precedence over its environment default and
is persisted in `data/`.

## Interface language

The onboarding wizard asks for the interface language. It can later be changed
under **Settings → Language and interface**.

Supported languages:

- German
- English
- Spanish
- French
- Italian
- Dutch
- Polish
- Portuguese
- Turkish
- Ukrainian

When the browser exposes a local translator API, translation runs there.
Otherwise, static source strings are sent to the server-side translator and
cached in `data/`. Without `UI_TRANSLATOR_URL`, the configured public fallback
is used. Set a LibreTranslate base URL for a fully self-hosted translation path.

## TMDB metadata

With a TMDB key, artwork, descriptions, genres, release dates, ratings, and
runtime prefer TMDB data. Providers remain responsible for discovery, hosters,
and downloads. If TMDB is unavailable or no reliable match exists, provider
metadata is retained automatically.

## Provider catalog

The onboarding wizard shows all providers after content-language selection.
Movie, series, and anime providers can be enabled and reordered independently.
The same controls are available later under **Settings → Provider catalog**.

The first enabled source has the highest priority. Discovery, automatic requests,
and download fallbacks use the same selection and ordering. Each provider's
content language is displayed and stored in every download job. A concrete
language reported by the selected hoster takes precedence.

## Updates

Docker images record their source revision before Git metadata is removed.
Folder- or archive-based NAS deployments can also identify recent `main`
revisions without a manual `APP_COMMIT_SHA`.

Two modes are available under **Settings → Updates**:

- **Manual:** show an install button when a new revision is available.
- **Automatic:** check GitHub on the configured interval and install only when
  downloads and download preparation are idle.

A busy queue defers the update and triggers a new check after queue completion.
A local development revision that diverges from `main` is never overwritten
automatically.

The installer downloads the exact offered GitHub revision, verifies and extracts
the archive, updates Python dependencies when required, writes the new build ID,
and restarts the server. It does not modify `data`, media directories,
`settings.ini`, or `.env`.

Compose keeps the active revision in `./runtime`. Mounted-folder deployments
update their persistent source directory directly. The install button remains
disabled when the active application directory is not persistent.

yt-dlp has a separate queue-safe update loop. It checks the stable channel on
its own interval and never replaces the executable during an active download.

## Telegram requests

1. Create a bot with `@BotFather`.
2. Enter the token under **Settings → Telegram**, enable the bot, and save.
3. Send `/start` to the bot. Until a chat ID is stored, it only returns the
   caller's ID and cannot start downloads.
4. Save the allowed chat ID.

A movie title such as `Titanic` is then enough. Royal Downloader checks
Jellyfin, searches the configured providers, downloads the movie, starts a
library scan, and reports completion.

Additional commands:

```text
/status  /speicher  /pfade  /abos  /jellyfin  /hilfe
```

Series request examples currently use German command keywords:

```text
The Rookie ALLES
The Rookie Staffel 8
The Rookie Staffel 8 EP 3
```

These request all missing episodes, one missing season, or one episode.

## Operational notes

- The first start takes longer because Chromium, ffmpeg, and Python packages may
  be installed. Later starts use existing packages or Docker layer caching.
- If a SerienStream episode is blocked by a Turnstile gate, the series fallback
  route tries other enabled providers.
- Local Windows startup remains available with `python server.py`; container
  behavior is controlled entirely through environment variables.
