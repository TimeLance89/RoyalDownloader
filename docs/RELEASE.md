# Release operations

[← Project overview](../README.md) · [Docker and NAS guide](DOCKER.md) ·
[Changelog](../CHANGELOG.md)

## Release status

The current official release is **`v1.0.0-rc.2`**. It is a release candidate,
not the final `v1.0.0`. It preserves the existing HTTP, `/api/v1`, WebSocket,
Docker, update, and persistent-data contracts, but should still be validated on
the target NAS before unattended operation.

External providers may change pages, domains, availability, or protection
mechanisms at any time. Provider health and fallback handling reduce the impact
but cannot guarantee third-party availability.

## Prerequisites

- Docker Engine and Docker Compose v2;
- Git for a version-pinned source checkout;
- writable persistent directories for `data/` and `runtime/`;
- separate writable Jellyfin movie and series directories;
- enough free space for media, staged runtime releases, and one rollback copy.

Do not expose port `8765` directly to the public internet. Do not publish
`.env`, settings, cookies, databases, API keys, tokens, private addresses,
chat IDs, media paths, or unsanitized logs in GitHub issues.

## Fresh Docker installation

```bash
git clone --branch v1.0.0-rc.2 --depth 1 https://github.com/TimeLance89/RoyalDownloader.git
cd RoyalDownloader
cp .env.example .env
mkdir -p data runtime
```

Edit `.env` and set at least absolute NAS paths for both media mounts:

```dotenv
PUID=1000
PGID=1000
MOVIES_HOST_DIR=/volume1/media/Filme
SERIES_HOST_DIR=/volume1/media/Serien
APP_REQUIRE_AUTH=true
```

The selected UID/GID must be able to write `data/`, `runtime/`, and both media
directories. Keep Jellyfin, TMDB, Telegram, Seerr, and provider mirror values
empty until they are intentionally configured.

```bash
sudo chown -R 1000:1000 data runtime
sudo chown -R 1000:1000 /volume1/media/Filme /volume1/media/Serien
docker compose config --quiet
APP_COMMIT_SHA="$(git rev-parse HEAD)" docker compose up -d --build
docker compose logs -f seriendownloader
```

In another terminal, verify liveness and version metadata:

```bash
curl --fail http://127.0.0.1:8765/api/health
curl --fail http://127.0.0.1:8765/api/v1/capabilities
```

The legacy health response remains `{"status":"ok"}`. Capabilities reports
`application_version` as `1.0.0-rc.2` and reports the source revision separately
as `build`.

## Persistent paths

| Host data | Container path | Purpose |
|---|---|---|
| `./data` | `/app/data` | Settings, sessions, queue, subscriptions, provider state, and integration state |
| `./runtime` | `/runtime` | Active, previous, and staged versioned application releases |
| `MOVIES_HOST_DIR` | `/movies` | Completed movies for Jellyfin |
| `SERIES_HOST_DIR` | `/serien` | Completed series for Jellyfin |
| `./data/seerr` | `/app/config` in Seerr | Seerr database and configuration |

Media directories must never rely on the container's ephemeral writable layer.

## Backup before an update

Drain or pause downloads when practical, then stop the stack before copying
mutable files:

```bash
docker compose down
backup_dir="../royal-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cp -a .env data runtime "$backup_dir"/
git rev-parse HEAD > "$backup_dir/source-commit.txt"
```

Back up movie and series libraries according to the storage system's own
snapshot policy. Do not copy Seerr SQLite files while Seerr is running.

## Upgrade from continuous `main`

This path moves an existing checkout that previously followed `main` to the
current versioned release candidate without changing persistent formats:

```bash
docker compose down
git fetch --tags origin
git status --short
git switch --detach v1.0.0-rc.2
APP_COMMIT_SHA="$(git rev-parse HEAD)" docker compose up -d --build
curl --fail http://127.0.0.1:8765/api/health
```

Stop if `git status --short` shows local source changes; preserve or review them
before switching. Do not delete `data/` or `runtime/`. The queue is restored
from persistent state after startup. Keep automatic application updates in
manual mode when the installation must remain pinned to the release candidate;
the in-app updater otherwise follows the selected channel. Existing
installations default to **Stable** (`main`). **Overnight** (`overnight`) is an
explicit development-channel opt-in; follow the
[channel switching and promotion guide](UPDATE_CHANNELS.md).

After the first health check, restart once and verify the same persistent state:

```bash
docker compose restart seriendownloader
curl --fail http://127.0.0.1:8765/api/health
```

Confirm the queue, subscriptions, Jellyfin settings, and media paths in the UI.

## Rollback

For a source-tag rollback, stop the stack, restore the previous source commit or
tag, and rebuild while keeping persistent data:

```bash
docker compose down
git switch --detach "$(cat ../royal-backup-YYYYMMDD-HHMMSS/source-commit.txt)"
APP_COMMIT_SHA="$(git rev-parse HEAD)" docker compose up -d --build
curl --fail http://127.0.0.1:8765/api/health
```

If a compatible source rollback is insufficient, stop the stack and restore
the backed-up `data/` and `runtime/` together. The existing in-app versioned
runtime can also atomically switch to its previous complete source and
dependency set through **Settings → Updates → Rollback** or:

```bash
docker compose run --rm seriendownloader \
  python /opt/seriendownloader/docker_bootstrap.py --rollback
docker compose up -d
```

Always verify `/api/health`, the displayed application version and build SHA,
queue recovery, and both media mounts after rollback.

Channel changes use the same staged runtime and rollback point. Returning from
Overnight to Stable is blocked behind an explicit confirmation when `main` is
older or diverged; persistent data is not removed or migrated by that switch.

## Protected release path

`main` and `overnight` are protected against direct changes, force-pushes, and
deletion. Pull requests must be current, resolve review conversations, and pass
the `verify` Quality check. The restrictions also apply to administrators.

The release workflow runs the complete Quality workflow before creating an
annotated tag and its GitHub Release. Both operations are idempotent, so a safe
rerun accepts only the same tag target and never duplicates an existing
Release. Tags with a semantic pre-release suffix, for example
`v1.0.0-rc.2`, are marked as pre-releases. A future stable tag such as
`v1.0.0` is not marked as a pre-release merely because it uses the same
workflow.
