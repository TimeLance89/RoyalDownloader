# Royal Announcements — encrypted transport and signed publication

This feature is **staged** and disabled for global publishing on ordinary
RoyalDownloader installations. The public repository contains the pinned
**Ed25519 public verification key only**, never the private key.

## Architecture

- Client installations fetch **https://royal-downloader.de/api/public/announcements/feed**
  from the **server side** over certificate-validated HTTPS. Redirects are
  refused and a bounded 3-second network timeout prevents blocked downloads.
- Clients verify every announcement's Ed25519 signature, including messages
  loaded from the local persistent cache. An untrusted or malformed response
  is rejected as a unit, and older verified content remains available offline.
- A background check is initiated by an authenticated browser viewing Royal
  and repeated every five minutes while that UI is mounted. Server requests
  run off the FastAPI event loop. A fully offline installation receives a
  message the next time a user opens Royal while the message is still retained.
- The Abo-Inbox displays official news and events without requiring a series
  subscription. Users explicitly mark an announcement read.
- Each installation's local administrator can disable receipt under
  **Einstellungen → Betrieb**; this persists across restarts in
  'announcements.sqlite3'. Disabled instances do not contact the publisher.
- Installation UUIDs and pseudonymous per-profile identifiers are transmitted
  with delivery/read confirmations. The publisher tracks distinct installations
  and profiles, not names, IP histories, media libraries, or Jellyfin accounts.
  Receipt statistics are **best-effort self-reports**, not attested measurements;
  malicious internet clients may forge them. A bounded public request rate
  and input checks reduce accidental/unwanted load, not deliberate Sybil attacks.
- There is no end-to-end message-content encryption: messages are meant to be
  public announcements, TLS encrypts traffic, and signatures establish origin.
  The local sqlite content is not encrypted at rest.

## Official publisher configuration (operator only)

The UI never accepts a publishing secret and local RD administrators are not
global publishers. On the **official** server, provision a private Ed25519 key
corresponding exactly to the public key pinned in
'application_services/announcements.py'. Do **not** place it in Git, web assets,
Docker images, volumes exposed by the web server, logs, or backups accessible
to untrusted people. Restrict its filesystem read permissions to the server
process. A mismatch disables publishing (fail closed).

Then configure these environment variables on the official backend:

\`\`\`dotenv
ROYAL_ANNOUNCEMENTS_PUBLISHER=1
ROYAL_ANNOUNCEMENTS_PRIVATE_KEY_FILE=/secure/path/publisher-private.pem
ROYAL_ANNOUNCEMENTS_OWNER_USER_ID=<id from authenticated GET /api/me>
\`\`\`

Additionally, access the official frontend on **royal-downloader.de** (not a
local IP/alternate host). The management UI appears in **Betrieb** only when
the browser has an authenticated administrator session whose exact user ID
matches the configured owner, the correct private key is readable, and the
request host is the official domain. Publishing/revocation is checked again
server-side on every request. A local admin on a third-party installation
cannot acquire this capability by setting a flag: without the pinned key's
private counterpart, a forged feed will be rejected by genuine clients.

The official domain's reverse proxy must serve the backend endpoints on the
same HTTPS origin. Configure HTTPS with a current TLS policy (TLS 1.3 preferred),
secure cookies, reliable host validation and authenticated administration.
Do not expose the announcement database or publisher private key through HTTP.

**Provisioning must be completed before activating reception in production.**
A public receiver with no reachable official publisher will simply show its
last verified cache and cannot provide newly published messages.

## API

| Route | Audience |
|---|---|
| GET /api/announcements | Authenticated local profile; signed local cache and own read flags |
| GET/POST /api/announcements/settings | Authenticated local account / local admin |
| POST /api/announcements/{uuid}/read | Authenticated local profile |
| GET /api/announcements/admin/status | Authenticated; indicates exact publisher ownership |
| GET/POST /api/announcements/admin/messages | Publisher owner only; stats and new messages |
| POST /api/announcements/admin/messages/{uuid}/revoke | Publisher owner only |
| GET /api/public/announcements/feed | Public signed messages; official publisher only |
| POST /api/public/announcements/receipts | Bounded pseudonymous public telemetry; official publisher only |

Payloads contain version, UUID, revision, title, body, category, created time,
optional expiration, revoked flag and Ed25519 signature. A revocation increments
revision and is also signed; clients reject older revisions. No HTML is rendered
from untrusted message bodies; the UI uses 'textContent'.

## Validation and rollout

- 'python -m pytest -q tests/test_announcements.py'
- 'python -m ruff check --select E9,F63,F7,F82 application_services/announcements.py api/api_announcements_router.py tests/test_announcements.py'
- 'python scripts/security_scan.py'
- The existing complete Python/Node/browser regression workflows must pass
  before promotion from this feature branch.
- Verify real domain routing and reverse proxy, actual TLS behavior, UGREEN
  responsiveness, permissions, message delivery to a second installation,
  reader-profile separation, opt-out, and offline/reconnect behavior.

Nothing in this feature migrates watchlists, changes download routing,
auto-deploys the publisher, or exposes the private signing key.
