# Stable and Overnight update channels

[← Documentation index](README.md)

Royal Downloader has two explicit source-update channels. **Stable** is the
recommended default for normal installations. **Overnight** is an opt-in
development and test channel.

| UI channel | Git branch | Intended use |
|---|---|---|
| Stable | `main` | Reviewed release candidates and stable releases |
| Overnight | `overnight` | Earlier fixes and development changes that passed CI but need practical testing |

The selected `update_channel` is stored in the existing persistent
`data/FilmeDownloader/settings.ini`. An installation without that key uses
`stable`; its updater therefore continues to read only `main`. The API exposes
both `update_channel` and the derived `update_branch`, so the UI and updater
cannot select different sources.

## Switching from Stable to Overnight

1. Back up `.env`, `data/`, and `runtime/`.
2. Open **Settings → Updates and maintenance**.
3. Select **Overnight** and acknowledge the development-channel warning.
4. Save settings and check for updates.
5. Install the offered `overnight` revision through the normal updater.

Overnight may change frequently and may contain defects not present on Stable.
It still uses the exact-commit download, staging, smoke check, atomic runtime
activation, queue-safe restart, and rollback flow. A passing CI run means the
automated gates succeeded; it is not a stability guarantee.

## Switching from Overnight to Stable

Select **Stable** and save. The updater compares the installed commit with
`main`. If `main` is behind the installed build or the histories have diverged,
the status is marked as a possible downgrade/branch change. Automatic
installation pauses and the user must explicitly confirm the target commit.

For Docker/NAS runtime installations, the new revision is staged and tested
before activation. `runtime/current` changes atomically and
`runtime/previous` keeps the previous complete source and dependency set.
Neither channel switching nor rollback deletes `data/`, `.env`, the queue,
configuration, or mounted media directories. Do not use `git reset`,
`git clean`, or delete persistent directories to change channels.

After switching, verify:

```bash
curl --fail http://127.0.0.1:8765/api/health
curl --fail http://127.0.0.1:8765/api/v1/updater/config
```

Then restart the container once and confirm that the channel, queue, and media
mounts remain unchanged.

## Sofortupdate per NAS-Paket

Wenn der laufende In-App-Updater selbst defekt oder zu alt ist, wird der
aktuelle Quellstand einmalig als geprüftes Transferpaket gebaut:

```bash
python scripts/build_nas_update.py --ref origin/overnight
```

Die erzeugte Datei `dist/RoyalDownloader-NAS-Update-<commit>.tar.gz` wird auf
das NAS kopiert und dort außerhalb des Projektordners entpackt. Anschließend:

```bash
mkdir -p /tmp/royal-update
tar -xzf RoyalDownloader-NAS-Update-<commit>.tar.gz -C /tmp/royal-update
bash /tmp/royal-update/install.sh /volume1/docker/RoyalDownloader
```

Der Zielpfad muss auf die vorhandene Installation mit `docker-compose.yml`,
`data/` und `runtime/` zeigen. Der Installer prüft den SHA-256 des Payloads,
sichert den bisherigen Quellstand, ersetzt ausschließlich Anwendungsdateien,
baut den Container neu und akzeptiert das Update erst, wenn exakt der
paketierte Commit als aktives Runtime-Release läuft. `.env`, `data/`,
`runtime/`, Downloads und Medien werden weder aufgenommen noch überschrieben.
Bei einem fehlgeschlagenen Start wird der vorherige Quellstand automatisch
wiederhergestellt.

Falls eine ältere Installation noch unter einem anderen Docker-Containernamen
läuft, wird dieser als zweites Argument übergeben. Der neue Container wird
zuerst gebaut; erst dann wird der alte gestoppt. Bei Fehlern startet der
Installer ihn wieder:

```bash
bash /tmp/royal-update/install.sh /volume1/Deluxe Downloader_Deluxe
```

## Development and promotion workflow

1. Develop feature/fix branches against `overnight`.
2. Merge reviewed changes into `overnight` only after the complete quality
   gates pass.
3. Test Overnight builds in practice and fix known regressions there.
4. Open a pull request from `overnight` to `main`.
5. Run the complete quality gates again on the promotion PR.
6. Merge deliberately into `main`; no workflow automatically promotes it.
7. Update the central application version and changelog on `main`.
8. Publish the Stable release or release candidate from a commit contained in
   `main`.

Both `main` and `overnight` run Python and frontend tests, syntax checks, Ruff,
Bandit, dependency audit, Docker build, health, persistence, and restart smoke
checks. The updater also checks the Quality result for the exact Overnight
commit and fails closed while it is pending, missing, or unsuccessful. The
release workflow additionally rejects tags whose commit is not an ancestor of
`main`.

Both permanent branches are protected on GitHub. Changes require a pull
request, the branch must be current, the `verify` status check must pass, and
review conversations must be resolved. These rules also apply to repository
administrators. Force-pushes and deletion of `main` or `overnight` are blocked.

No registry image is introduced by this channel model. If images are added
later, release tags and `stable` belong to Stable; Overnight may use
`overnight` and `overnight-<commit>`. Release candidates must never update
`latest`.
