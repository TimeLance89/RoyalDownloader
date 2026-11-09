# Media center and Jellyfin playback

[← Project overview](../README.md) · [Docker and NAS](DOCKER.md) ·
[v2.1.0 release notes](releases/v2.1.0.md)

RoyalDownloader connects discovering, downloading and watching media in one
web interface. The integrated browser player uses your Jellyfin library and
streaming server. You can continue to use browsing, requests and downloads
without setting up playback.

## Before you start

- Run RoyalDownloader v2.1.0 or newer and a working Jellyfin server.
- Ensure the Royal host/container can reach Jellyfin at its configured address.
- Have an administrator configure the Jellyfin connection and API key in Royal's
  media-center settings.
- Link each participating Royal account to the appropriate Jellyfin profile in
  household settings. That profile must be enabled, allowed to play media and
  able to see the selected film or episode.

A container's `localhost` is that container, not a different Jellyfin container
or the NAS host. Use an address reachable from the Royal service. Browser
playback reaches Royal's authenticated stream endpoints; upstream media-server
credentials are retained on the server.

## Connect the household

1. An administrator opens the media-center settings and configures **Jellyfin**.
2. Check the connection, library selection and existing media inventory.
3. In household settings, assign the intended Jellyfin profile to each Royal
   account that should watch content.
4. Sign in as that member and open an available title.

Both enabled members and administrators can play content. Connection management
stays administrator-only. An ordinary account without a linked Jellyfin profile
does not gain access through the server administrator's default profile.

For separate playback positions, use **separate Jellyfin profiles**. If two Royal
accounts intentionally share one Jellyfin profile, they also share that
profile's watched state and progress. Download jobs and physical media storage
remain shared server resources.

## Start a film

Open the film's detail view. When an accessible matching item is available in
Jellyfin, the play button starts it in Royal. A partly watched item offers the
saved time instead. Royal checks the linked profile's access before preparing
the stream; an ownership ribbon alone does not grant playback permission.

The player provides:

- play/pause, a seekable timeline and elapsed/total time;
- backward/forward skips of 10 seconds;
- volume, mute and playback speed;
- fullscreen with controls that return on pointer/keyboard activity;
- picture-in-picture when supported by the browser.

Keyboard shortcuts: **Space** or **K** for play/pause, **Left/Right** to skip,
**M** to mute and **F** for fullscreen. Shortcuts respect editable controls.
Fullscreen uses the browser's supported presentation mechanism; available
controls can vary on mobile platforms.

## Browse seasons and episodes

Series details combine available Jellyfin episodes with the download view.
Choose a season and inspect the available episodes, their watched state and
saved progress. Missing episodes remain part of the separate download workflow.

Inside the player, previous/next episode controls and the episode menu let you
navigate the available series. The menu includes season selection. Known gaps
leave the corresponding navigation action unavailable rather than silently
jumping to an unrelated episode.

## Continue watching

The Home carousel lists resumable films and episodes from the linked Jellyfin
profile. Cards identify the saved time and, for series, the episode. Clicking
one opens playback directly.

The card menu offers:

| Action | Effect |
| --- | --- |
| Open details | Opens the corresponding film or series with its library context |
| Remove from Continue watching | Hides the entry from your Royal list, retaining its Jellyfin progress |
| Mark as watched | Updates the watched state in your linked Jellyfin profile |
| Undo | Reverses a recent supported action while its undo option is available |

Hiding a card never deletes the media file. New playback activity may make a
hidden item resumable again. Marking it watched affects the linked Jellyfin
profile, so consider shared-profile mappings when setting up your household.

Progress is periodically saved during playback and on pause/close when possible.
Abruptly closing a browser or losing connectivity can leave the most recent
seconds unsaved. Reopen the title to read the server's current position.

## What Royal and Jellyfin each do

| RoyalDownloader | Jellyfin |
| --- | --- |
| Discovery, personal Home, requests and download management | Library indexing and media availability |
| Detail views, season navigation and browser player UI | Stream preparation, direct play and transcoding |
| Profile-bound stream proxy and progress requests | Per-profile visibility, playback rights and watched state |
| Continue watching actions and personal hiding | Resume positions and watched history |

Royal uses Jellyfin-negotiated direct play or HLS. HLS resources are served
through private Royal session URLs, including nested playlists and segments.
The browser player does not expose the configured Jellyfin API key.

Server load and network speed still affect startup, buffering and seeking.
Jellyfin needs sufficient transcoding capacity when direct play is unavailable.
A browser or server that cannot handle a format cannot be made universally
compatible by enabling the player in Royal.

## Access and session changes

Every playback session is bound to the RD account/session, current media-server
configuration and linked Jellyfin profile. Requests for streams, progress,
images, details and episode navigation are checked against that context and the
visible item. Changing accounts or the media-center connection clears personal
player state. Old sessions cannot be reused by a different account.

Each new HLS resource request checks access again. Long open streams check local
session/account state before subsequent chunks at most every two seconds and
remote profile/item permissions at most every ten seconds. Previously delivered
or buffered data cannot be withdrawn. A revoked session may therefore leave a
small amount of already buffered video visible before new delivery stops.

## Plex and segment metadata

The [Plex integration](PLEX.md) retains its documented library, list and request
features. The browser player described here uses Jellyfin.

Royal also provides authenticated read access to existing Jellyfin Intro/Outro
markers for clients. Detection and analysis stay in Jellyfin or its configured
tools. The web player gains no new skip controls from this backend API. Empty
or unsupported results are handled explicitly. See
[the segment API guide](JELLYFIN_MEDIA_SEGMENTS.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Available title cannot be played | The current account's Jellyfin mapping, enabled profile, playback permission and item visibility |
| No Continue watching row | Correct linked profile, an actual partly watched item, and whether the entry was hidden or marked watched |
| Wrong or shared position | Whether household accounts are linked to the same Jellyfin profile |
| Player stops after switching account/server | Reopen it under the new account and connection; old contexts are intentionally invalidated |
| Buffering or slow seeking | Jellyfin logs, transcoding resources and network connection; compare with playback in Jellyfin |
| Fullscreen or picture-in-picture unavailable | Browser/platform support and allowed browser permissions |
| Jellyfin unavailable from a container | The configured server address, container network and connection test in media-center settings |

Existing installations should back up persistent data and review the
[v2.1.0 upgrade notes](releases/v2.1.0.md#upgrade) before updating. Never include
API keys, authentication cookies, private server addresses or media paths in
public diagnostic reports.
