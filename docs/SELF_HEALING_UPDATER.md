# Self-healing Docker updater (Overnight)

The existing versioned updater still downloads, validates, stages and atomically
activates releases under `APP_RUNTIME_DIR`. This extension does **not** introduce
a second downloader, a Docker socket, a privileged sidecar or a new update API.

## Independent supervisor

`container_entrypoint.py` first checks unprivileged mount access, then starts
`updates/docker_bootstrap.py` from the **Docker image**. The bootstrap creates
or selects the existing `runtime/current` symlink. Instead of replacing itself
with `server.py`, it remains alive and runs `updates/runtime_guard.py` to start
the active runtime as a child subprocess.

The child inherits `ROYAL_GUARD_CHILD=1`. On a normal in-app update, its
existing restart callback re-execs the image bootstrap **in that same child**;
the marker prevents nesting another supervisor. One image-owned supervisor
remains independent of all subsequently downloaded runtime source files.

The guard polls local `/api/health` and `/api/v1/capabilities`. When a release
contains `.app_commit_sha`, the *running* process build must match its prefix.
The generic health endpoint alone cannot confirm that a newly activated release
was actually started. Startup must succeed within 120 seconds by default,
configurable with `ROYAL_STARTUP_TIMEOUT_SECONDS` (30–600). Once healthy,
normal runtime execution continues without periodic restarts or external probes.

## Durable recovery intent

`APP_RUNTIME_DIR/.update-recovery.json` contains only schema, known-good
release name, pending release name, blocked release and a short reason. No
tokens, settings, personal data or media paths are stored. The file is written
using a private temporary file, `fsync` and atomic rename, followed by a
directory `fsync` on POSIX.

Before changing `current`, the existing installer writes **pending** with
the previous complete release. The guard marks the candidate healthy only
after its exact running revision passes both local checks. If the process
exits before readiness, cannot launch, or misses its deadline, the guard
persists a **failed/blocked** record, stops the process, and uses the existing
`rollback_release` symlink operation to activate `previous` once. Then it
launches the known-good runtime. The same failed revision is refused on later
automatic and manual update attempts until explicitly addressed.

A power loss before activation leaves the previous current runtime intact;
once it starts healthy, the stale intent is cleared. A power loss **after
failure is journaled but before the rollback symlink changes** is completed
on the next Docker start. An invalid/corrupt journal is not silently erased.
Only releases proven to be the recorded previous/current pair are considered
for automatic recovery; unknown destinations are never deleted or activated.

A normal shutdown or failure *without* a pending candidate does not cause
an arbitrary rollback. Failed candidate recovery is bounded to one rollback
attempt per watchdog run; if both versions fail, the container exits with an
error so operators can investigate. No update loop or repeated bad activation
is attempted.

## Deployment and verification

**Important:** the independent bootstrap and guard live in the Docker image.
An application-only in-app update cannot replace an already-running image's
immutable bootstrap. Rebuild and restart the image after merging this change:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 seriendownloader
```

Do this first in a maintenance window after backing up `.env`, `data/` and
`runtime/`. Existing media mounts, queues, profile data, provider settings,
HTTP endpoints and web interface are unchanged. The healthcheck in Compose
remains active independently.

Regression tests: `python -m pytest -q tests/test_runtime_guard.py
tests/test_runtime_release.py tests/test_updater_robustness.py`.
The normal protected-branch CI additionally exercises Docker startup,
persistent state, upgrades, backups and rollback.

## Boundaries

- The guard is in the **application container**, not the NAS host. It cannot
  repair an unavailable Docker daemon, host filesystem, broken image,
  inaccessible mount, missing recovery release or a failing Docker service.
- Readiness verifies the application's existing health and build identity,
  not the health of every external provider or integration.
- Source-only legacy updates outside the versioned `APP_RUNTIME_DIR` remain
  non-atomic and are not covered by this guard.
- NAS-specific power-loss testing and permission checks must be performed
  separately; deterministic tests do not prove tolerance of every possible
  power-loss timing or underlying filesystem fault.
- Recovery results are available in container logs and the small local
  journal. They deliberately do not require an operational HTTP API.
