# Personal RD → Jellyfin watchlist

1. Persist movie/TV wishes by authenticated RD user and TMDB identity. Saving never queues downloads. Unlinked profiles retain pending wishes.
2. Reconcile only playable items visible to the linked Jellyfin user into a private, RD-managed video playlist. Keep pending wishes after outages and restart; reconcile removals and mapping changes. Never match by title alone.
3. Add “+ Merken” / “Gemerkt ✓” to film and series details with pending/error feedback and cancellation on navigation.
4. Extend the experimental Android TV patch with a native Jellyfin home row. Read only the current Jellyfin user's reserved playlist, collapse episodes into series cards, refresh on resume/library changes and clear on profile switches. No RD credentials are needed for this row.
5. Test persistence, separate users, unavailable libraries, delayed imports, removals, remakes and movie/TV ID collisions. Validate UI and the upstream Android patch/build. Submit separate PRs to overnight and experiment/jellyfin-firetv-rd.

The managed playlist uses the reserved name `RD-Merkliste · <Jellyfin user UUID>` so even Jellyfin administrators never select another profile's list by its display name. The home row displays just “RD-Merkliste”. Keep that reserved playlist name; its contents are managed by RD. Requires Jellyfin's modern private playlist API (10.10+); unsupported servers retain RD wishes and report a sync failure.

Library reads use the linked user's visibility and exclude virtual/offline placeholders. Episode reads are restricted to exactly matched saved series. The background worker retries every 30 seconds and keeps the existing playlist on read failures. Bindings use Jellyfin's stable server ID, so changing a server URL does not create a second list. RD wishes remain separate if multiple RD users link to the same Jellyfin user; that one viewer's native list contains their combined available wishes.
