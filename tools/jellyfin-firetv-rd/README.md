# Jellyfin Android TV + RoyalDownloader search prototype

Experimental Fire TV integration built from upstream Jellyfin Android TV `v0.19.10`.

Behavior:
- The home screen always shows a personal **RD-Merkliste** row for the active Jellyfin user. Available contents use native movie/series posters. Empty lists explain that saved titles appear after import; loading failures stay visible with an OK-to-retry action. RD creates a private video playlist named `RD-Merkliste · <Jellyfin user UUID>`; the UUID suffix prevents cross-profile name collisions, including for administrators, and is hidden in native playlist cards/details.
- Movies open their normal Jellyfin details; multiple episodes of a saved series appear as one series card. The row clears on profile switches and refreshes on resume, library events and every 30 seconds while visible. No RD login is required for this row.
- Pending wishes remain in RD until Jellyfin has imported playable files. Requires the RD personal-watchlist backend and Jellyfin 10.10+; saving itself does not request a download.
- Jellyfin search continues to work normally.
- RoyalDownloader is queried in parallel through `/api/v1`.
- RD results already present in Jellyfin are filtered with `/api/v1/jellyfin/matches`.
- Selecting a movie enqueues its provider slug in RD.
- Selecting a series resolves the series and queues missing released episodes only.
- If RD is not configured (or the connection fails), selecting the RoyalDownloader setup/error card opens a small URL/username/password dialog.
- The debug build has the separate Android application id `org.jellyfin.androidtv.debug` and app name `Jellyfin RD 0.4`, so it can coexist with the normal Jellyfin release app.

The integration is applied by `patch_jellyfin.py` during GitHub Actions. The upstream Jellyfin source is not vendored into RoyalDownloader.
