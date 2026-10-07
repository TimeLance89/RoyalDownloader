# Privacy Egress

Royal's existing interface, API contracts, providers and workflows remain intact.
The outbound transport selects routing beneath them. No anonymity guarantee is
made; an egress provider can see connection metadata and remains a trusted party.

## Configuration

```env
ROYAL_EGRESS_MODE=privacy
ROYAL_EGRESS_PROXY=http://proxy.example:3128
ROYAL_EGRESS_LOCAL_BYPASS=true
```

- `direct` (default): existing routing and environment proxy behavior are retained.
- `privacy`: all migrated external HTTP(S) transports use the local validating
  Network Guard, which connects only to the configured HTTP or HTTPS CONNECT proxy.
- `ROYAL_EGRESS_PROXY_FILE`: alternative readable file containing the entire proxy
  URL. Configure either the file or the URL, not both. Percent-encode special
  characters in credentials. HTTPS proxy TLS certificates are verified.
- Privacy mode is always fail-closed. Missing/invalid configuration, DNS errors,
  rejected tunnels and offline proxies fail through existing error paths. There
  is **never an automatic direct retry** and no option to disable this invariant.
- `local_bypass=true`: explicitly local integration endpoints remain direct.
  Disabling it routes them to the guard, which rejects private targets; do not
  disable this setting when LAN integrations are required.

The original SSRF guard is retained. Public IP validation, mixed-answer rejection,
restricted HTTP(S) ports and redirects apply at its connection boundary. The
upstream proxy receives a validated **literal IP**, avoiding a second provider
hostname resolution and DNS rebinding. Origin HTTPS TLS/SNI stays end-to-end.
If a tunnel fails, the guard sequentially tries the remaining validated A/AAAA
addresses through the same egress manager and proxy. If all attempts fail, it
returns the existing connection error; it never opens a direct target socket.
Proxy credentials are used only inside that boundary, never passed to Chromium,
yt-dlp command lines or ordinary application clients. Error messages are sanitized.

## Local and external targets

Classification uses the URL hostname, without resolving DNS. Loopback, RFC1918,
IPv6 ULA, link-local, single-label Docker/NAS names, `localhost`, `.localhost`,
`.local`, `.lan`, `.home`, `.internal`, `.home.arpa` and `.fritz.box` are local.
Public domain names remain external even if DNS returns a private address.
Reserved/documentation addresses are not treated as integration LAN addresses.

Requests used by providers and curl_cffi transports always retain the external
guard boundary; local-looking provider URLs cannot use the integration bypass.
Requests policy runs at every redirect hop. urllib propagates the external guard
requirement through redirects so a remote redirect cannot turn into LAN access.
Jellyfin, Seerr, Ollama and a local LibreTranslate endpoint use direct LAN routing.

## Outbound inventory

| Transport/path | Before | Privacy behavior |
| --- | --- | --- |
| Provider curl_cffi sessions, CachedHTTP/source_utils, TMDB embeds, calendar | Some direct; some explicit guard | Compatible central curl transport, guard then egress |
| requests providers (AniWorld/Mkissa), hoster probes | Direct or explicit guard | Provider transport always guarded |
| SessionManager, extractor, sentinel probes/repairs | Local guard connecting directly | Same guard; chained external egress |
| MP4/HLS/DASH downloads and fallback curl streaming | yt-dlp/selected curl via guard | Entire HTTP transfer via chained guard |
| yt-dlp simulations and subscription optimizer | Explicit guard | Guard plus inherited proxy environment for ffmpeg descendants |
| ffprobe/media quality | Direct or guard environment | Central proxy environment for network sources |
| Chromium/nodriver, shared sessions, verification | Local guard or direct isolated sidecar | Guard, no implicit loopback bypass, QUIC disabled, non-proxied WebRTC UDP disabled, direct DNS disabled |
| TMDB, Telegram (urllib) | Direct/system environment | Policy opener, including redirect hops |
| Translation, releases, GitHub updater | Direct requests sessions/functions | Central requests transport |
| PyPI/yt-dlp/self-update pip subprocesses | Direct/system environment | Guard proxy environment including PIP_PROXY |
| NAS bootstrap apt/pip | Direct | Lifetime-managed guard subprocess wrapper |
| Jellyfin, Seerr, Ollama, live playback probes | Direct/system environment | Explicit LAN bypass or external guard |
| CDP HTTP/WebSocket, local CDP reverse proxy | Local browser control channel | Local control channel; browser's Internet traffic separately guarded |
| Docker health checks | Loopback | Remain local |

## DNS

In privacy mode provider DNS validation uses Cloudflare DNS-over-HTTPS through
the **same configured proxy**, connecting to resolver IP `1.1.1.1` and verifying
the `cloudflare-dns.com` certificate. Both A and AAAA answers are checked; every
address must be public. Answers are cached up to their TTL, capped at 60 seconds,
and validated IPs are pinned when connecting. There is no system-DNS fallback.
The proxy must permit CONNECT to the DoH resolver and public destination IPs.

System DNS remains necessary for local service names and, if the proxy is named,
for resolving the proxy itself. Use a literal proxy IP to avoid that bootstrap
query (HTTPS proxies then need a certificate valid for that IP). Existing
`DNS_PRIMARY`/`DNS_SECONDARY` settings remain compatible in direct mode. Privacy
NAS startup skips resolver overrides and the old external DNS diagnostic.
Compose's system resolver settings affect local/bootstrap resolution only.

## Docker and browser recovery

Compose passes the policy to the application **and** isolated `royal-browser`.
The browser launcher keeps its own loopback guard alive throughout Chromium's
lifetime. Cookies, browser profiles, CDP and recovery workflows keep their
existing lifecycle. Proxy secrets can be mounted read-only into **both** services
using a Compose override and `ROYAL_EGRESS_PROXY_FILE=/run/secrets/egress_proxy`.
Do not mount Royal data or API credentials into the browser container.

An arbitrary remotely managed browser cannot have its network policy enforced
from CDP alone. Privacy recovery therefore requires local Chromium or the managed
Compose `royal-browser:9222` endpoint; other CDP endpoints fail closed. Keep the
browser container rebuilt and configured with the same policy as the application.

## Known limitations

- The user's WebUI browser is a separate network client. Existing Google Fonts,
  TMDB images/logo, YouTube embeds, avatars and external links keep their existing
  client-side routing. Configure that browser/device separately when its traffic
  must also use an egress; this backend policy does not proxy it or change the UI.
- This is application transport policy, not an OS/container firewall. Manual
  commands, third-party services (including Seerr's own outbound traffic), Docker
  image pulls and future new network clients require their own configuration.
  Add an egress firewall for protection against arbitrary code/native bypasses.
- Browser flags constrain supported browser traffic; they do not replace a
  firewall. An independently launched or outdated browser is outside this policy.
- Local-name routing assumes operator-configured integration endpoints. Do not
  repurpose provider transports for local services or accept untrusted integration
  configuration. Provider private URLs are always rejected by the guard.
- Proxy CONNECT must support public IP targets on ports 80/443. SOCKS proxies,
  PAC files and non-HTTP media transports are not supported by this policy.
- ffmpeg builds must honor HTTP proxy environment settings for HTTP and HTTPS.
  yt-dlp's ffmpeg inputs receive a protocol allowlist. Verify the deployed native
  build, container and proxy with real downloads before enabling unattended use.
- Initial privacy bootstrap with an HTTPS proxy requires urllib3 already present
  for verified TLS-in-TLS DNS transport; missing support fails closed. HTTP proxy
  bootstrap uses only the Python standard library.
- Mock/local transport tests cannot certify live provider availability, CAPTCHA
  recovery, native browser builds, or your proxy. No full-anonymity claim is made.

Transport references: [Chromium proxy behavior](https://github.com/chromium/chromium/blob/main/net/docs/proxy.md),
[FFmpeg protocols](https://www.ffmpeg.org/ffmpeg-protocols.html),
[curl_cffi session API](https://curl-cffi.readthedocs.io/en/stable/api.html).
