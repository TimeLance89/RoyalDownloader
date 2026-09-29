# Jellyfin Android TV + RoyalDownloader search prototype

Experimental Fire TV integration built from upstream Jellyfin Android TV `v0.19.10`.

Behavior:
- Jellyfin search continues to work normally.
- RoyalDownloader is queried in parallel through `/api/v1`.
- RD results already present in Jellyfin are filtered with `/api/v1/jellyfin/matches`.
- Selecting a movie enqueues its provider slug in RD.
- Selecting a series resolves the series and queues missing released episodes only.
- If RD is not configured (or the connection fails), selecting the RoyalDownloader setup/error card opens a small URL/username/password dialog.
- The debug build has the separate Android application id `org.jellyfin.androidtv.debug` and app name `Jellyfin RD`, so it can coexist with the normal Jellyfin release app.

The integration is applied by `patch_jellyfin.py` during GitHub Actions. The upstream Jellyfin source is not vendored into RoyalDownloader.
