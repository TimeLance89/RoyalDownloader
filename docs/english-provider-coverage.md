# English provider coverage (2026-10-03)

The six active adapters use RD's TMDB search, series hierarchy, provider health,
hoster selection, source resolution and download queue. Mirror domains remain
within one adapter. `scripts/probe_english_providers.py` checks three films and
four episodes with bounded manifest/range reads; it downloads no media files.

| Family | Active | Domains / failover | Film / TV | Streams and audio | Live smoke |
| --- | --- | --- | --- | --- | --- |
| VidSrc | Yes | `data.vidsrc.sh`, `data.vidsrcme.ru`; public embeds `vidsrc.sh` | TMDB, exact S/E | Signed HLS, audio from playlist when declared; CDN token | 3/3 films; 0/4 TV in batch, 1/1 S01E01 when retried separately |
| VixSrc | Yes | `vixsrc.to` | TMDB, exact S/E | HLS, FHD flag, English/Italian audio tracks | 7/7 |
| VidRift | Yes | `embed.vidrift.net`, `embed.vidrift.in` | TMDB, exact S/E | Selfhost/Evion/Orion/Warm HLS or MP4; language when declared or present in playlist | 4/7; remaining titles had no source |
| VidRock | Yes | `vidrock.net`; optional `VIDROCK_MIRRORS` | TMDB, exact S/E | Dynamic server list, HLS/MP4, language and quality when declared | 7/7 |
| VidLink | Yes | `vidlink.pro`; DASH CDN fallback from `noon.mooncase.online` to `flood.sourcerrr.online` | TMDB, exact S/E | Browser network capture to signed DASH/HLS/MP4; MPD audio language/quality when declared | 6/7; Succession S03E05 unavailable |
| MovieBox / AoneRoom | Yes | `api6`, `api5`, `api4`, `api4sg`, `api3.aoneroom.com` | TMDB title/year/type match, exact S/E | HLS/MP4/MKV/DASH, language, signed Cookie | 6/7; Succession S03E05 unavailable |
| VidFast | No | `vidfast.vc`, older `vidfast.pro` | Embed accepts TMDB film/TV paths | Player POSTs encrypted probe and per-server unlock; no local Python resolver verified | No direct media URL verified |

VidLink's current `/api/b/...` needs a player-generated encoded ID. The local
browser fallback captures the player's signed MPD without an external decrypt
service; its CDN mirror is retried after a failed stream probe. VidFast was tested
against its current embed and RD's browser extractor, which did not yield a
usable media URL: the embed returns HTTP 200 to a regular request, but its
browser player showed a Cloudflare block and made no player API requests.
`vidfast.pro` redirects to `vidfast.vc`. Recent reference implementations replay VidFast's obfuscated
player bundle in Node or delegate encryption to `enc-dec.app`. Neither approach
meets this task's local, independent Python resolver requirement. VidFast remains
absent from the catalog until film, series and reachable-stream checks pass.
No DRM or paywall handling was added.

The active adapters keep `Referer`, `Origin`, stream type, language and optional
Cookie in `HosterInfo`; the existing source resolver and yt-dlp download pipeline
receive these fields. MovieBox DASH was additionally accepted by RD's actual
`probe_stream_url` simulation (`index.mpd`, 2026-10-03). This is a manifest
probe, not a complete download test. VidSrc's TV API is intermittently unavailable
under a rapid series of requests, and VidRift has title gaps.
