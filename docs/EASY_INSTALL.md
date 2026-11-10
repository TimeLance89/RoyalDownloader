# RoyalDownloader Easy Install – Windows and NAS

> **Beta**: The installer is currently being validated. The Windows `.exe` is built
> from an exact Git commit by the `Build Windows Easy Installer` workflow. Do not
> confuse this app installer with the separate Fire TV APK.

## Download and start

1. Download **`RoyalDownloader-Setup.exe`** together with its SHA-256 checksum
   from the corresponding GitHub workflow artifact. After an approved stable
   release, download it from that release's assets.
2. Verify the checksum if possible; Windows Defender and SmartScreen may warn
   about a newly published, not yet code-signed community binary. **Do not turn
   off Windows security features.** Check the publisher/release provenance
   before choosing whether to run it. The installer is currently **not digitally
   code-signed**.
3. Double-click the executable and choose **Windows-PC** or **NAS / Heimserver**.

The installer contains **the exact checked-out RoyalDownloader source revision**
for Windows (ZIP) and NAS (tar.gz). The integrity of both archives is verified
before installation; the NAS archive is additionally checked again after SSH
transfer. Nothing is pulled from an arbitrary download server.

### Install on the Windows computer

- The installer itself needs no system-wide Python environment.
- The RoyalDownloader **server application** currently requires **Python 3.12**.
  If Python 3.12 is unavailable, the prerequisite step explains where to get
  it. The server packages are installed only into a private `.venv` inside
  the selected new program directory (never global pip).
- Provide a **new, previously non-existent program directory** and separate
  movie/series folders. Existing program directories are intentionally rejected;
  this is a new-install flow, not an upgrade/repair tool.
- Confirm the non-destructive prerequisite check and then the installation.
- Use the generated **`RoyalDownloader starten.cmd`** to launch Royal locally.
  The application listens on `127.0.0.1:8765` only.
- Chrome/Chromium and FFmpeg are needed for particular provider/extraction or
  download formats. Install them when prompted if these functions are needed.
  Existing installations are unaffected.

### Install on an NAS from a Windows PC

**Prerequisites:** A supported x86-64 Linux NAS, enabled SSH, an ordinary SSH
account that is allowed to run Docker and Docker Compose v2 **without sudo**,
`tar`, `sha256sum`, `curl`, and at least 2 GiB free on the installation volume.
This mode was designed for Linux NAS systems such as UGREEN UGOS Pro; exact NAS
vendor-specific Docker interfaces and permission policies vary.

1. Choose **NAS** in the first step.
2. Enter the NAS address and SSH port. **First retrieve the SSH host key**.
3. Verify the displayed SHA-256 fingerprint against a **trusted, independent
   source** such as the locally administered NAS. For a Linux shell, the server's
   fingerprint can normally be checked with
   `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. If the fingerprint differs,
   cancel. An unverified SSH key can belong to an attacker.
4. Select password or SSH private-key authentication. Credentials are used only
   for the SSH session and are **not written to disk** by Royal Setup.
5. Choose the **new** Royal application folder, and the **existing** movie and
   series folders (NAS host paths, e.g. `/volume1/Filme`). The latter are mapped
   to `/movies` and `/serien` inside Docker without any recursive `chown` or
   `chmod`. Existing UGOS ACLs remain untouched.
6. Run the checks. The installer refuses to continue if host paths, Docker
   permissions, architectures, project names, image prerequisites or port 8765
   are not suitable.
7. Confirm the installation. Royal Setup uploads the pinned source package over
   SSH/SFTP, verifies SHA-256 on the NAS, creates **only a new project folder**,
   generates `.env` with safe paths and a one-time setup code, and runs
   `docker compose -p royaldownloader-easy up -d --build seriendownloader`.
   The isolated browser sidecar starts as a dependency; optional Seerr is **not
   started by default**.
8. When the health check succeeds, open `http://<NAS-IP>:8765` on your LAN and
   finish the personal web onboarding. The installer provides the one-time code
   directly – you do **not** need to search through logs.

**Security boundaries:** No automatic SSH host-key acceptance, no `sudo` or root
SSH account, no Docker socket exposure to the Internet, no public port forward,
no mutation of existing containers, no recursive modification of media ownership.
Docker group membership effectively grants host administrator capabilities:
use only your own NAS and trusted accounts. For remote playback over the Internet,
set up an authenticated secure reverse proxy/tunnel separately.

## What happens on failure?

- Before installation, every check is read-only (apart from the SSH trust pin
  saved **after** the operator confirms the fingerprint).
- Failed Windows preparation removes only the uniquely named scratch folder.
  When application files have already been placed into their final fresh folder,
  they are left in place for diagnosis instead of touching unrelated data.
- Failed NAS preparation removes only its uniquely named temporary directory.
  When the fresh Royal project has already been created, it remains available
  for diagnosis. **No existing media directories are deleted or modified.**
- No installation step silently removes unrelated Docker containers or project
  stacks. If an earlier installation exists, use the documented upgrade or
  backup/migration flow instead of Easy Install.

## Maintainers: build the executable

Windows CI produces a one-file `.exe`, packaged by PyInstaller from
`RoyalDownloader-Setup.pyw`. Both source archives are generated by `git archive`
from **exactly the same checkout**, and the checksums are stored in
`source-manifest.json` inside the executable.

```powershell
py -3.12 -m pip install -r installer/requirements-installer.txt
py -3.12 -m installer.build_source
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name RoyalDownloader-Setup --add-data "installer/assets;installer/assets" `
  --collect-all paramiko --hidden-import tkinter RoyalDownloader-Setup.pyw
.\dist\RoyalDownloader-Setup.exe --self-test
```

The executable is distributed through a GitHub Actions artifact or release
asset. **Do not commit large unsigned build binaries to the source root.**
The corresponding source entrypoint lives in the root as
`RoyalDownloader-Setup.pyw`; the build command emits the standalone file
`dist/RoyalDownloader-Setup.exe` (also the top-level file of the ZIP artifact).

## Limitations / further QA required

- The GUI and core unit tests can run on Linux; a real `.exe` requires a Windows
  runner. CI tests package integrity without a NAS connection. A real new PC
  and a real NAS should be used for acceptance testing before stable release.
- SSH private keys protected by passphrases and Windows SSH agent integration
  depend on the selected Paramiko authentication path; private-key files are
  accepted, but the installer does **not** store any passphrase.
- There is no unattended migration of existing Royal installations; backups,
  upgrades, and recovery remain separate operations.
- ARM NAS models are intentionally blocked until the project image's browser
  and security-floor requirements have been validated on those architectures.
- Initial Docker image builds can take significant time and require access to
  the configured operating-system and Python package registries.

For troubleshooting, [Docker & NAS](DOCKER.md),
[upgrade and rollback](RELEASE.md), and [media-center setup](MEDIA_CENTER.md)
remain authoritative.
