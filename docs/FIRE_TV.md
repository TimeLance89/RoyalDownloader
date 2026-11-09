# Fire TV app

[← Project overview](../README.md#fire-tv-app) · [Media center](MEDIA_CENTER.md)

## Download

**[RoyalDownloader TV v2.0.49 — native APK](https://github.com/TimeLance89/RoyalDownloader/releases/download/v2.1.0/RoyalDownloader-TV-2.0.49-native.apk)**

[Download the SHA-256 checksum](https://github.com/TimeLance89/RoyalDownloader/releases/download/v2.1.0/RoyalDownloader-TV-2.0.49-native.apk.sha256)

The TV client is attached to the **v2.1.0 server release**. Its own version is
**2.0.49**; TV-client and server versions are independent. This is the supplied
APK, published without modifying, rebuilding or re-signing it.

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
| File | `RoyalDownloader-TV-2.0.49-native.apk` |
| App version | `2.0.49` |
| Version code | `20049` |
| Package | `de.royaldownloader.tv` |
| Size | `4,136,749` bytes |
| Signature | APK Signature Scheme v2, verified |
| Signing certificate | Android Debug (`CN=Android Debug, O=Android, C=US`) |

This supplied package uses an **Android Debug signing certificate**, verified
with `apksigner`. Its SHA-256 checksum identifies the exact file being distributed:

```text
746998c7e1f15cf9ecf33d035bfb3b0838836e9229b5d99fa19fc747c19a7b87  RoyalDownloader-TV-2.0.49-native.apk
```

Certificate SHA-256:

```text
a555b9e566768b3e5dc8ac71d88d3048aa7ea1b22b616c8a2710562b1a400814
```

On Windows:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\RoyalDownloader-TV-2.0.49-native.apk
```

On Linux, with the APK and checksum in the same directory:

```bash
sha256sum --check RoyalDownloader-TV-2.0.49-native.apk.sha256
```

Validation covers package metadata, archive integrity and the APK signature.
Live playback on a Fire TV remains untested.
