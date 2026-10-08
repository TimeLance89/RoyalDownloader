# Jellyfin Android TV + RoyalDownloader search prototype

Experimental Fire TV integration built from upstream Jellyfin Android TV `v0.19.10`.

Behavior:
- The home screen always shows a personal **RD-Merkliste** row for the active Jellyfin user. Available contents use native movie/series posters. Empty lists explain that saved titles appear after import; loading failures stay visible with an OK-to-retry action. RD creates a private video playlist named `RD-Merkliste · <Jellyfin user UUID>`; the UUID suffix prevents cross-profile name collisions, including for administrators, and is hidden in native playlist cards/details.
- Movies open their normal Jellyfin details; multiple episodes of a saved series appear as one series card. The row clears on profile switches and refreshes on resume, library events and every 30 seconds while visible. No RD login is required for this row.
- Pending wishes remain in RD until Jellyfin has imported playable files. Requires the RD personal-watchlist backend and Jellyfin 10.10+; saving itself does not request a download.
- The toolbar has a dedicated **RD durchsuchen** button. It opens a separate RD-only screen with the upstream TV keyboard/voice input, visible loading/empty/error states and an **RD verbinden** button. Submit retries the same query; changing the query cancels obsolete results.
- Jellyfin search continues to work normally and does not wait for RD.
- The dedicated screen searches movies and series in parallel through `/api/v1`.
- RD results already present in Jellyfin are filtered with `/api/v1/jellyfin/matches`.
- Selecting a movie asks for confirmation before enqueuing its provider slug in RD. Repeated clicks cannot submit the same result concurrently.
- Selecting a series asks for confirmation, resolves the series and queues missing released episodes only. A partial series library match does not hide the search result. Pending, unavailable or stale library checks block the request until a reliable check is possible.
- If RD is not configured (or the connection fails), selecting the RoyalDownloader setup/error card opens a small URL/username/password dialog.
- RD API v1 compatibility is checked before searching. Passwords are held only for login; successful sessions retain the bearer token. Expired sessions require login and never silently replay download requests. HTTP redirects are rejected to keep credentials on the configured origin. LAN HTTP URLs are supported; use HTTPS for remote servers.
- The debug build has the separate Android application id `org.jellyfin.androidtv.debug` and app name `Jellyfin RD 0.5`, so it can coexist with the normal Jellyfin release app. The build explicitly sets upstream version `0.19.10` instead of falling back to `0.0.0-dev.1`.

The integration is applied by `patch_jellyfin.py` during GitHub Actions. The upstream Jellyfin source is not vendored into RoyalDownloader.

## Remaining prototype gaps

- RD download progress/history and retry/cancel controls are not yet displayed in the APK.
- RD result cards do not load provider artwork yet.
- Pending personal-watchlist wishes can only be managed in RD; the native row shows imported playable media.
- Discovery genres, subscriptions, season/episode selection and anime are not part of the dedicated search yet.
- Builds are debug APKs without a managed persistent distribution signing key or in-app updater.
- D-pad/keyboard behavior and actual requests need a physical Fire TV smoke test. Unit tests and an APK build do not verify device behavior.

Overnight already provides the API v1 capabilities, queue, match statuses and series availability/staleness fields used here. No backend changes are required for this screen.
