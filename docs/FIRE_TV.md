# Fire TV app

[← Project overview](../README.md#fire-tv-app) · [Media center](MEDIA_CENTER.md)

## Download

**[RoyalDownloader TV v2.0.54 — native APK](https://github.com/TimeLance89/RoyalDownloader/releases/download/v2.1.0/RoyalDownloader-TV-2.0.54-native.apk)**

[Download the SHA-256 checksum](checksums/RoyalDownloader-TV-2.0.54-native.apk.sha256)

The TV client is intended to be distributed as an asset of the **v2.1.0 server release**. Its own version is
**2.0.54**; TV-client and server versions are independent. This is the supplied
APK; it should be published without modifying, rebuilding or re-signing it.

## Installation

1. Download the APK and, if desired, verify it against the checksum below.
2. Transfer/install the APK on your Fire TV using your APK installation method.
3. Open the TV app and connect it to your running RoyalDownloader server. The
   server address must be reachable from the Fire TV.

The APK declares minimum Android API level **25** and a TV launcher entry.
Its manifest disables cleartext traffic: use a reachable **HTTPS** Royal server
address with a certificate trusted by the TV device.

Keep your existing server accounts and configuration. An app update must be
signed by the same certificate as the installed app to update it in place.

## Package and integrity

| Field | Supplied APK |
| --- | --- |
| File | `RoyalDownloader-TV-2.0.54-native.apk` |
| App version | `2.0.54` |
| Version code | `20054` |
| Package | `de.royaldownloader.tv` |
| Size | `4,165,638` bytes |
| Signature | APK Signature Scheme v2 present |
| Signing certificate | Android Debug (`CN=Android Debug, O=Android, C=US`) |

This supplied package uses an **Android Debug signing certificate**, identified
from its APK v2 signing block. Its SHA-256 checksum identifies the exact file being distributed:

```text
9c93ba7a465127eb2835925e7204cc002cf602cd46cd3d3efe584da1e6474ff5  RoyalDownloader-TV-2.0.54-native.apk
```

Certificate SHA-256:

```text
a555b9e566768b3e5dc8ac71d88d3048aa7ea1b22b616c8a2710562b1a400814
```

On Windows:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\RoyalDownloader-TV-2.0.54-native.apk
```

On Linux, with the APK and checksum in the same directory:

```bash
sha256sum --check RoyalDownloader-TV-2.0.54-native.apk.sha256
```

The supplied file's manifest, archive integrity and embedded signing certificate
were inspected; this does not replace an on-device installation test.
Live playback on a Fire TV remains untested.
