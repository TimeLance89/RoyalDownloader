using System.IO;
using System.Security.Cryptography;
using System.Text;
using Renci.SshNet;

namespace RoyalDownloader.Setup.Native;

/// <summary>
/// Manages only the isolated Compose project created by this manager.
/// All remote calls use pinned SSH host keys and shell-quoted paths.
/// Never touches movies/series or arbitrary NAS containers.
/// </summary>
internal static class NasManager
{
    private const string ProjectName = "royaldownloader-easy";
    private static string Q(string value) => NasInstaller.Quote(value);
    private static string Run(SshClient ssh, string command, int timeout = 60) =>
        NasInstaller.Execute(ssh, command, timeout);

    private static void CheckOwner(SshClient ssh, NasOptions cfg)
    {
        string root = Q(cfg.Project);
        string marker = Q(cfg.Project + "/" + ManagerEngine.Marker);
        Run(ssh, "set -eu; test -d " + root + "; test ! -L " + root +
            "; test -f " + marker + "; test ! -L " + marker +
            "; grep -Fq '\"owner\":\"RoyalDownloaderManager\"' " + marker +
            "; grep -Fq '\"platform\":\"nas\"' " + marker +
            "; test -f " + Q(cfg.Project + "/docker-compose.yml") +
            "; test -f " + Q(cfg.Project + "/.env"));
        string labels = Run(ssh, "docker ps -a --filter label=com.docker.compose.project=" +
            ProjectName + " --format '{{.Label \"com.docker.compose.project.working_dir\"}}'");
        var entries = labels.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        if (entries.Any(dir => dir.Trim() != cfg.Project))
            throw new InvalidOperationException("Docker meldet eine fremde Compose-Arbeitsmappe. Es werden keine Container verändert.");
    }

    internal static string Preflight(NasOptions cfg, ManagerAction action)
    {
        if (action == ManagerAction.Install) return NasInstaller.Preflight(cfg);
        InstallerEngine.ValidateNas(cfg);
        InstallerEngine.VerifyResources();
        using var ssh = NasInstaller.Connect(cfg);
        CheckOwner(ssh, cfg);
        Run(ssh, "docker compose version >/dev/null; docker info --format '{{.ServerVersion}}' >/dev/null");
        if (action == ManagerAction.Update)
        {
            string parent = cfg.Project[..cfg.Project.LastIndexOf('/')];
            string usage = Run(ssh, "df -Pk " + Q(parent) + " | tail -1");
            string[] parts = System.Text.RegularExpressions.Regex.Split(usage.Trim(), @"\s+");
            if (parts.Length < 4 || !long.TryParse(parts[3], out var freeKb) || freeKb < 3L * 1024 * 1024)
                throw new InvalidOperationException("Für das NAS-Update müssen 3 GiB frei sein.");
        }
        return action switch
        {
            ManagerAction.Repair => "Hostschlüssel bestätigt; eigene Compose-Dienste und Projektmarker erkannt. Rebuild ohne Medienänderungen möglich.",
            ManagerAction.Update => "Hostschlüssel bestätigt; kontrollierter Quellstand-Wechsel mit Wiederherstellungskopie möglich.",
            ManagerAction.Uninstall => "Hostschlüssel bestätigt; ausschließlich die eigenen Compose-Dienste werden beendet. Eine Datenkopie bleibt am NAS.",
            _ => throw new ArgumentOutOfRangeException(nameof(action))
        };
    }

    private static void Upload(SftpClient client, byte[] content, string remoteFile)
    {
        using var stream = new MemoryStream(content);
        client.UploadFile(stream, remoteFile, true);
    }

    private static string NewSibling(string path, string suffix)
        => path + "." + suffix + "-" + DateTimeOffset.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" +
           Convert.ToHexString(RandomNumberGenerator.GetBytes(3)).ToLowerInvariant();

    internal static InstallResult Manage(NasOptions cfg, ManagerAction action,
        IProgress<string> log, CancellationToken cancellation)
    {
        if (action == ManagerAction.Install)
        {
            var latest = StableSource.FetchLatestAsync(log, cancellation).GetAwaiter().GetResult();
            return NasInstaller.Install(cfg, log, cancellation, latest);
        }

        _ = Preflight(cfg, action);
        using var ssh = NasInstaller.Connect(cfg);
        CheckOwner(ssh, cfg);
        string project = Q(cfg.Project);
        const string service = "seriendownloader";
        if (action == ManagerAction.Repair)
        {
            cancellation.ThrowIfCancellationRequested();
            log.Report("Docker Compose prüft und baut die bestehenden Royal-Dienste neu …");
            Run(ssh, "set -eu; cd " + project +
                "; docker compose -p " + ProjectName + " up -d --build " + service, 3600);
            log.Report("Reparatur ausgeführt. Medienverzeichnisse und persistente Daten wurden nicht verändert.");
            return new InstallResult("http://" + cfg.Host + ":8765", "", cfg.Project);
        }
        if (action == ManagerAction.Uninstall)
        {
            cancellation.ThrowIfCancellationRequested();
            string backup = NewSibling(cfg.Project, "deinstalliert-daten-gesichert");
            log.Report("Nur die eigenen Royal-Container und deren Compose-Netzwerke werden beendet …");
            Run(ssh, "set -eu; cd " + project +
                "; docker compose -p " + ProjectName + " down", 90);
            Run(ssh, "set -eu; test ! -e " + Q(backup) +
                "; mv -- " + project + " " + Q(backup));
            log.Report("RoyalDownloader entfernt. Daten, Einstellungen und Projektdateien verbleiben als Rückfallsicherung: " + backup);
            return new InstallResult("", "", backup);
        }

        // A failed GitHub request must not stop existing containers.
        var release = StableSource.FetchLatestAsync(log, cancellation).GetAwaiter().GetResult();
        string parent = cfg.Project[..cfg.Project.LastIndexOf('/')];
        string stage = NewSibling(parent + "/.royal-manager-update", "stage");
        string archive = NewSibling(cfg.Project, "version-backup");
        string qStage = Q(stage), qBackup = Q(archive);
        bool stageCreated = false, stopped = false, oldMoved = false, newMoved = false;
        try
        {
            cancellation.ThrowIfCancellationRequested();
            byte[] tar = release.Tar;
            string hash = Convert.ToHexString(SHA256.HashData(tar)).ToLowerInvariant();
            Run(ssh, "set -eu; test ! -e " + qStage +
                "; test ! -e " + qBackup + "; mkdir -m 700 -- " + qStage);
            stageCreated = true;
            log.Report("Geprüften Quellstand per SFTP übertragen …");
            using (var sftp = NasInstaller.ConnectSftp(cfg))
            {
                Upload(sftp, tar, stage + "/royal-source.tar.gz");
                Upload(sftp, Encoding.UTF8.GetBytes(ManagerEngine.CreateMarker("nas", release.Commit)),
                    stage + "/" + ManagerEngine.Marker);
            }
            string verified = Run(ssh,
                "sha256sum " + Q(stage + "/royal-source.tar.gz") + " | cut -d' ' -f1");
            if (!string.Equals(verified, hash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Übertragenes Quellarchiv hat eine falsche Prüfsumme.");
            Run(ssh, "set -eu; tar -xzf " + Q(stage + "/royal-source.tar.gz") +
                " -C " + qStage + " --no-same-owner --no-same-permissions; " +
                "rm -- " + Q(stage + "/royal-source.tar.gz") + "; " +
                "cp -p -- " + Q(cfg.Project + "/.env") + " " + Q(stage + "/.env") + "; " +
                "cd " + qStage + "; docker compose -p " + ProjectName + " config --quiet", 120);
            cancellation.ThrowIfCancellationRequested();
            log.Report("Eigene Docker-Container anhalten, Daten danach geschützt übernehmen …");
            Run(ssh, "set -eu; cd " + project + "; docker compose -p " + ProjectName + " down", 120);
            stopped = true;
            Run(ssh, "set -eu; test ! -e " + qBackup + "; mv -- " + project + " " + qBackup);
            oldMoved = true;
            Run(ssh, "set -eu; test ! -e " + project + "; mv -- " + qStage + " " + project);
            newMoved = true;
            Run(ssh, "set -eu; " +
                "for n in data runtime; do " +
                "if [ -e " + Q(archive) + "/$n ] && [ ! -e " + Q(cfg.Project) + "/$n ]; then " +
                "mv -- " + Q(archive) + "/$n " + Q(cfg.Project) + "/$n; fi; " +
                "done");
            log.Report("Neue Image-Version wird gebaut, vorherige Version bleibt gesichert …");
            Run(ssh, "set -eu; cd " + project +
                "; docker compose -p " + ProjectName + " up -d --build " + service, 3600);
            log.Report("Aktualisierung abgeschlossen; Wiederherstellungskopie: " + archive);
            return new InstallResult("http://" + cfg.Host + ":8765", "", cfg.Project);
        }
        catch (Exception error)
        {
            if (stopped)
            {
                log.Report("Update fehlgeschlagen. Versuche ursprüngliches Projekt wiederherzustellen …");
                try
                {
                    if (newMoved)
                    {
                        Run(ssh, "set -eu; " +
                            "for n in data runtime; do " +
                            "if [ -e " + project + "/$n ] && [ ! -e " + qBackup + "/$n ]; then " +
                            "mv -- " + project + "/$n " + qBackup + "/$n; fi; done");
                        Run(ssh, "mv -- " + project + " " + Q(NewSibling(cfg.Project, "fehlgeschlagen")));
                    }
                    if (oldMoved)
                        Run(ssh, "mv -- " + qBackup + " " + project);
                    Run(ssh, "set -eu; cd " + project +
                        "; docker compose -p " + ProjectName + " up -d " + service, 120);
                }
                catch (Exception rollback)
                {
                    log.Report("Wiederherstellung fehlgeschlagen: " + rollback.Message +
                        " – bitte Sicherungsordner manuell prüfen.");
                }
            }
            throw new InvalidOperationException("NAS-Aktualisierung nicht abgeschlossen: " + error.Message, error);
        }
        finally
        {
            if (stageCreated && !newMoved)
                log.Report("Nicht verwendeter Staging-Ordner bleibt zur Fehlerdiagnose: " + stage);
        }
    }
}