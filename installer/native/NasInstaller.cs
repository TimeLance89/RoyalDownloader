using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Renci.SshNet;
using Renci.SshNet.Common;

namespace RoyalDownloader.Setup.Native;

/// <summary>
/// Only fresh installations on x86_64 NAS devices. Never changes existing media ACLs,
/// existing project directories, installed images or Docker containers.
/// </summary>
internal static class NasInstaller
{
    internal sealed record NasPreflight(int UserId, int GroupId, string Architecture);

    public static string Fingerprint(byte[] hostKey) =>
        "SHA256:" + Convert.ToBase64String(SHA256.HashData(hostKey)).TrimEnd('=');

    private static bool SameFingerprint(string actual, string expected)
    {
        byte[] left = Encoding.ASCII.GetBytes(actual), right = Encoding.ASCII.GetBytes(expected);
        return left.Length == right.Length && CryptographicOperations.FixedTimeEquals(left, right);
    }

    public static string ProbeHostKey(NasOptions config)
    {
        InstallerEngine.ValidateNas(config, false);
        string? fingerprint = null;
        // No user's password is supplied during this phase. Host trust is always
        // refused; this handshake only retrieves the public SSH host key.
        using var ssh = new SshClient(config.Host, config.Port, config.Username, "not-a-real-credential");
        ssh.ConnectionInfo.Timeout = TimeSpan.FromSeconds(12);
        ssh.HostKeyReceived += (_, e) =>
        {
            fingerprint = Fingerprint(e.HostKey);
            e.CanTrust = false;
        };
        try { ssh.Connect(); }
        catch (SshException) { }
        catch (SshConnectionException) { }
        if (fingerprint is null)
            throw new InvalidOperationException("SSH-Hostschlüssel konnte nicht abgefragt werden.");
        return fingerprint;
    }

    private static void RequireTrust(NasOptions config, byte[] key)
    {
        string found = Fingerprint(key);
        if (!SameFingerprint(found, config.PinnedFingerprint))
            throw new InvalidOperationException("SSH-Hostschlüssel stimmt nicht mit dem bestätigten Fingerabdruck überein. Verbindung abgebrochen.");
    }

    private static SshClient Connect(NasOptions config)
    {
        InstallerEngine.ValidateNas(config);
        var client = new SshClient(config.Host, config.Port, config.Username, config.Password);
        client.ConnectionInfo.Timeout = TimeSpan.FromSeconds(18);
        client.HostKeyReceived += (_, e) =>
        {
            try { RequireTrust(config, e.HostKey); e.CanTrust = true; }
            catch { e.CanTrust = false; }
        };
        client.Connect();
        if (!client.IsConnected)
            throw new InvalidOperationException("SSH-Anmeldung fehlgeschlagen.");
        return client;
    }

    private static SftpClient ConnectSftp(NasOptions config)
    {
        var client = new SftpClient(config.Host, config.Port, config.Username, config.Password);
        client.ConnectionInfo.Timeout = TimeSpan.FromSeconds(18);
        client.OperationTimeout = TimeSpan.FromMinutes(8);
        client.HostKeyReceived += (_, e) =>
        {
            try { RequireTrust(config, e.HostKey); e.CanTrust = true; }
            catch { e.CanTrust = false; }
        };
        client.Connect();
        if (!client.IsConnected)
            throw new InvalidOperationException("SFTP-Verbindung fehlgeschlagen.");
        return client;
    }

    public static string Quote(string value)
    {
        if (value.Contains('\0')) throw new InvalidOperationException("Ungültiger Shell-Pfad.");
        return "'" + value.Replace("'", "'\\''") + "'";
    }

    private static string Execute(SshClient client, string command, int seconds = 40)
    {
        using var remote = client.CreateCommand(command);
        remote.CommandTimeout = TimeSpan.FromSeconds(seconds);
        string text = remote.Execute();
        if (remote.ExitStatus != 0)
        {
            string error = remote.Error.Trim();
            if (error.Length > 600) error = error[..600];
            throw new InvalidOperationException("NAS-Prüfung fehlgeschlagen (" +
                remote.ExitStatus + "). " + error);
        }
        return text.Trim();
    }

    private static NasPreflight PreflightConnected(NasOptions cfg, SshClient client)
    {
        string data = Execute(client,
            "set -eu; command -v docker >/dev/null; docker compose version >/dev/null; " +
            "docker info --format '{{.ServerVersion}}' >/dev/null; " +
            "command -v tar >/dev/null; command -v sha256sum >/dev/null; " +
            "command -v curl >/dev/null; uname -m; id -u; id -g");
        string[] lines = data.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        if (lines.Length < 3)
            throw new InvalidOperationException("NAS-Eigenschaften konnten nicht bestimmt werden.");
        string arch = lines[^3].Trim();
        if (arch != "x86_64" && arch != "amd64")
            throw new InvalidOperationException("Aktuell sind ausschließlich x86_64-NAS-Systeme freigegeben.");
        if (!int.TryParse(lines[^2], out int uid) || !int.TryParse(lines[^1], out int gid)
            || uid == 0 || gid == 0)
            throw new InvalidOperationException("Bitte als normaler NAS-Benutzer mit Docker-Rechten anmelden, nicht als root.");
        string project = Quote(cfg.Project);
        string movies = Quote(cfg.Movies);
        string series = Quote(cfg.Series);
        string parent = Quote(cfg.Project[..cfg.Project.LastIndexOf('/')]);
        Execute(client, "set -eu; test ! -e " + project + "; " +
            "test -d " + parent + "; test -w " + parent + "; " +
            "test -d " + movies + "; test -w " + movies + "; " +
            "test -d " + series + "; test -w " + series);
        string containers = Execute(client, "docker ps -a --format '{{.Names}}'");
        var names = new HashSet<string>(
            containers.Split('\n', StringSplitOptions.RemoveEmptyEntries),
            StringComparer.Ordinal);
        if (names.Contains("seriendownloader") || names.Contains("royal-browser"))
            throw new InvalidOperationException("Ein RoyalDownloader-Docker-Container existiert schon. Kein Überschreiben erlaubt.");
        string compose = Execute(client, "docker compose ls --format json");
        if (compose.Contains("\"royaldownloader-easy\"", StringComparison.Ordinal))
            throw new InvalidOperationException("Ein RoyalDownloader-Compose-Projekt ist schon vorhanden.");
        string? usedPort = Execute(client, "(command -v ss >/dev/null && ss -ltnH) || true");
        if (usedPort.Split('\n').Any(line =>
            Regex.IsMatch(line, @"(?<![0-9])(?:\:|\.)(8765)(?:\s|$)")))
            throw new InvalidOperationException("Port 8765 ist auf dem NAS bereits belegt.");
        string usage = Execute(client, "df -Pk " + parent + " | tail -1");
        string[] cells = Regex.Split(usage.Trim(), @"\s+");
        if (cells.Length < 4 || !long.TryParse(cells[3], out long availableKb) ||
            availableKb < 2L * 1024 * 1024)
            throw new InvalidOperationException("Weniger als 2 GiB freier Speicher für das NAS-Projekt.");
        return new NasPreflight(uid, gid, arch);
    }

    public static string Preflight(NasOptions cfg)
    {
        InstallerEngine.ValidateNas(cfg);
        InstallerEngine.VerifyResources();
        using var client = Connect(cfg);
        var p = PreflightConnected(cfg, client);
        return "SSH-Hostschlüssel bestätigt · Docker Compose erreichbar · " +
               "x86_64 · UID " + p.UserId + " / GID " + p.GroupId +
               " · bestehende Medien unverändert · Port 8765 geprüft.";
    }

    public static InstallResult Install(NasOptions cfg, IProgress<string> log,
        CancellationToken cancellation)
    {
        InstallerEngine.ValidateNas(cfg);
        InstallerEngine.VerifyResources();
        using var client = Connect(cfg);
        var preflight = PreflightConnected(cfg, client);
        string token = InstallerEngine.NewToken();
        string parent = cfg.Project[..cfg.Project.LastIndexOf('/')];
        string stage = parent + "/.royal-staging-" +
            Convert.ToHexString(RandomNumberGenerator.GetBytes(8)).ToLowerInvariant();
        string qstage = Quote(stage), qproject = Quote(cfg.Project);
        bool madeStage = false, committed = false;
        try
        {
            cancellation.ThrowIfCancellationRequested();
            log.Report("Neues isoliertes NAS-Projekt wird vorbereitet …");
            Execute(client, "set -eu; test ! -e " + qstage +
                "; test ! -e " + qproject + "; mkdir -m 700 -- " + qstage);
            madeStage = true;

            string source = stage + "/royal-source.tar.gz";
            byte[] tar = InstallerEngine.Resource("RoyalSource.tar.gz");
            string expected = Convert.ToHexString(SHA256.HashData(tar)).ToLowerInvariant();
            log.Report("Quellarchiv wird verschlüsselt mit SFTP übertragen …");
            using (var sftp = ConnectSftp(cfg))
            using (var stream = new MemoryStream(tar))
                sftp.UploadFile(stream, source, true);
            cancellation.ThrowIfCancellationRequested();
            string verified = Execute(client,
                "sha256sum " + Quote(source) + " | cut -d' ' -f1");
            if (!string.Equals(verified, expected, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Die Prüfsumme auf dem NAS stimmt nicht überein.");

            log.Report("Docker-Konfiguration wird geschützt eingerichtet …");
            Execute(client, "set -eu; tar -xzf " + Quote(source) +
                " -C " + qstage + " --no-same-owner --no-same-permissions; " +
                "rm -- " + Quote(source) + "; mkdir -p " + qstage + "/data " + qstage + "/runtime", 90);
            var env = new Dictionary<string, string>
            {
                ["ROYAL_DEPLOYMENT_MODE"] = "nas",
                ["HOST"] = "0.0.0.0",
                ["ROYAL_BIND_ADDRESS"] = "0.0.0.0",
                ["OPEN_BROWSER"] = "0",
                ["PUID"] = preflight.UserId.ToString(),
                ["PGID"] = preflight.GroupId.ToString(),
                ["DOWNLOAD_DIR"] = "/movies",
                ["SERIES_DIR"] = "/serien",
                ["MOVIES_HOST_DIR"] = cfg.Movies,
                ["SERIES_HOST_DIR"] = cfg.Series,
                ["ROYAL_SETUP_TOKEN"] = token,
                ["SEERR_ENABLED"] = "false",
                ["UPDATE_CHANNEL"] = "stable",
                ["UPDATE_MODE"] = "manual",
                ["UPDATE_GITHUB_BRANCH"] = "main",
                ["JELLYFIN_URL"] = "",
                ["JELLYFIN_API_KEY"] = ""
            };
            byte[] envBytes = Encoding.UTF8.GetBytes(InstallerEngine.RenderEnv(env));
            using (var sftp = ConnectSftp(cfg))
            using (var stream = new MemoryStream(envBytes))
                sftp.UploadFile(stream, stage + "/.env", true);
            Execute(client, "chmod 600 -- " + Quote(stage + "/.env"));
            Execute(client, "set -eu; cd " + qstage +
                "; docker compose -p royaldownloader-easy config --quiet", 50);

            // Atomic publish only when checks pass; existing projects are never removed.
            cancellation.ThrowIfCancellationRequested();
            Execute(client, "set -eu; test ! -e " + qproject +
                "; mv -- " + qstage + " " + qproject);
            committed = true;

            log.Report("Docker-Image wird erstellt und RoyalDownloader gestartet …");
            Execute(client, "set -eu; cd " + qproject +
                "; docker compose -p royaldownloader-easy up -d --build seriendownloader", 3600);
            log.Report("Prüfe die RoyalDownloader-Gesundheitsschnittstelle …");

            bool healthy = false;
            for (int i = 0; i < 18; i++)
            {
                cancellation.ThrowIfCancellationRequested();
                Thread.Sleep(5000);
                try
                {
                    string health = Execute(client,
                        "curl -fsS --max-time 3 http://127.0.0.1:8765/api/health", 8);
                    if (health.Contains("\"ok\"") || health.Contains("\"status\""))
                    {
                        healthy = true; break;
                    }
                }
                catch (InvalidOperationException) { }
            }
            if (!healthy)
                throw new InvalidOperationException("Docker wurde gestartet, aber der Gesundheitscheck war nicht erfolgreich.");
            return new InstallResult("http://" + cfg.Host + ":8765", token, cfg.Project);
        }
        catch (Exception error)
        {
            if (madeStage && !committed)
            {
                try
                {
                    Execute(client, "test ! -e " + qproject +
                        " && rm -rf -- " + qstage + " || true", 40);
                }
                catch { /* Preserve the original error. */ }
            }
            throw new InvalidOperationException(error.Message + (committed ?
                " Das neue Docker-Projekt bleibt für die Diagnose erhalten; bestehende Installationen wurden nicht verändert." :
                " Bereits vorhandene NAS-Ordner wurden nicht verändert."), error);
        }
    }
}