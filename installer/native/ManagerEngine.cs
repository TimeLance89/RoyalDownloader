using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RoyalDownloader.Setup.Native;

internal enum ManagerAction { Install, Repair, Update, Uninstall }

/// <summary>
/// Safety boundary: only projects bearing the explicit manager marker are eligible
/// for repair/update/uninstall. Media paths are always external to the install root.
/// No global Python, registry, PATH, or unrelated containers are touched.
/// </summary>
internal static class ManagerEngine
{
    internal const string Owner = "RoyalDownloaderManager";
    internal const string Marker = ".royal-manager.json";
    private static readonly string[] Retained = [".env", "data", "runtime", "config", "logs"];
    internal static string OperationName(ManagerAction action) => action switch
    {
        ManagerAction.Install => "Neu installieren",
        ManagerAction.Repair => "Reparieren",
        ManagerAction.Update => "Aktualisieren",
        ManagerAction.Uninstall => "Deinstallieren",
        _ => "Unbekannt"
    };
    internal static string SourceCommit()
    {
        using var manifest = JsonDocument.Parse(InstallerEngine.Resource("SourceManifest"));
        return manifest.RootElement.GetProperty("commit").GetString() ?? "";
    }

    internal static string CreateMarker(string platform)
        => JsonSerializer.Serialize(new Dictionary<string, object>
        {
            ["owner"] = Owner,
            ["platform"] = platform,
            ["schema"] = 1,
            ["source_commit"] = SourceCommit(),
            ["created_utc"] = DateTimeOffset.UtcNow.ToString("O"),
            ["instance_id"] = Guid.NewGuid().ToString("N")
        });

    internal static void SaveMarker(string root, string platform)
    {
        string path = Path.Combine(root, Marker);
        if (File.Exists(path)) throw new InvalidOperationException("Bereits verwaltete Installation vorhanden.");
        File.WriteAllText(path, CreateMarker(platform), Encoding.UTF8);
    }

    internal static void CheckWindowsMarker(string root)
    {
        string marker = Path.Combine(root, Marker);
        if (!Directory.Exists(root) || !File.Exists(marker))
            throw new InvalidOperationException("Keine vom Royal-Manager angelegte Installation gefunden. Es wird nichts verändert.");
        if (new DirectoryInfo(root).Attributes.HasFlag(FileAttributes.ReparsePoint))
            throw new InvalidOperationException("Verlinkte Projektordner sind nicht zulässig.");
        using var document = JsonDocument.Parse(File.ReadAllText(marker));
        var data = document.RootElement;
        if (data.GetProperty("owner").GetString() != Owner ||
            data.GetProperty("platform").GetString() != "windows" ||
            data.GetProperty("schema").GetInt32() != 1 ||
            !File.Exists(Path.Combine(root, "server.py")) ||
            !File.Exists(Path.Combine(root, ".env")))
            throw new InvalidOperationException("Projektmarker oder Installation ist beschädigt. Keine Änderungen.");
    }

    internal static string CheckManagedWindows(WindowsOptions options, ManagerAction operation)
    {
        if (string.IsNullOrWhiteSpace(options.Project) || !Path.IsPathFullyQualified(options.Project))
            throw new InvalidOperationException("Ein vollständiger Windows-Projektpfad ist erforderlich.");
        string root = Path.GetFullPath(options.Project);
        if (Path.GetPathRoot(root)!.Equals(Path.TrimEndingDirectorySeparator(root),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Ein ganzes Laufwerk darf nicht verwaltet werden.");
        if (operation == ManagerAction.Install)
            return InstallerEngine.WindowsPreflight(options);
        CheckWindowsMarker(root);
        InstallerEngine.VerifyResources();
        if (operation == ManagerAction.Update &&
            new DriveInfo(Path.GetPathRoot(root)!).AvailableFreeSpace < 3L * 1024 * 1024 * 1024)
            throw new InvalidOperationException("Für die gesicherte Aktualisierung werden 3 GiB freier Speicher benötigt.");
        return operation switch
        {
            ManagerAction.Repair => "Verwaltete Installation gefunden. Private Python-Pakete können repariert werden; Daten und Programmcode bleiben erhalten.",
            ManagerAction.Update => "Verwaltete Installation gefunden. Eine gesicherte, versionierte Aktualisierung wird vorbereitet. Daten, Konfiguration und Medien bleiben erhalten.",
            ManagerAction.Uninstall => "Verwaltete Installation gefunden. Royal wird gestoppt und aus dem aktiven Programmordner entfernt. Ein lokales Wiederherstellungsarchiv bleibt bestehen; Medien werden nicht gelöscht.",
            _ => throw new ArgumentOutOfRangeException(nameof(operation))
        };
    }

    private static bool IsWithin(string directory, string candidate)
    {
        string root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        string target = Path.TrimEndingDirectorySeparator(Path.GetFullPath(candidate));
        return target.Equals(root, StringComparison.OrdinalIgnoreCase) ||
            target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    internal static string ArchiveName(string root, string suffix)
        => root + "." + suffix + "-" + DateTimeOffset.Now.ToString("yyyyMMdd-HHmmss") +
            "-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(3)).ToLowerInvariant();

    internal static void RequireFreePort()
    {
        var listener = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 8765);
        try { listener.Start(); }
        catch (SocketException error)
        {
            throw new InvalidOperationException(
                "Port 8765 ist bereits belegt. Bitte RoyalDownloader oder den betreffenden Dienst zuerst beenden.", error);
        }
        finally { listener.Stop(); }
    }

    private static async Task StartOwnedServer(string root, IProgress<string> log, CancellationToken cancel)
    {
        RequireFreePort();
        string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python))
            throw new InvalidOperationException("Die private Python-Laufzeit ist nicht vorhanden.");
        var info = new ProcessStartInfo(python)
        {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
        };
        info.ArgumentList.Add(Path.Combine(root, "server.py"));
        using var child = Process.Start(info) ??
            throw new InvalidOperationException("RoyalDownloader-Server konnte nicht gestartet werden.");
        RememberOwnedServer(root, child);
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        for (int attempt = 0; attempt < 30; attempt++)
        {
            cancel.ThrowIfCancellationRequested();
            await Task.Delay(1000, cancel);
            try
            {
                using var res = await http.GetAsync("http://127.0.0.1:8765/api/health", cancel);
                if (res.IsSuccessStatusCode) { log.Report("RoyalDownloader wurde wieder gestartet."); return; }
            }
            catch (HttpRequestException) { }
            catch (TaskCanceledException) when (!cancel.IsCancellationRequested) { }
        }
        StopOwnedServer(root, log);
        throw new InvalidOperationException("Der RoyalDownloader-Server hat den Gesundheitscheck nicht bestanden.");
    }

    private static void StopOwnedServer(string root, IProgress<string> log)
    {
        string identity = Path.Combine(root, "royal-server.pid");
        if (!File.Exists(identity)) return;
        string[] pidAndStart = File.ReadAllText(identity).Trim().Split('|');
        if (pidAndStart.Length != 2 || !int.TryParse(pidAndStart[0], out int pid))
            throw new InvalidOperationException("Ungültige PID-Verwaltung. Bitte Royal manuell schließen.");
        try
        {
            using var proc = Process.GetProcessById(pid);
            string expectedExe = Path.GetFullPath(Path.Combine(root, ".venv", "Scripts", "python.exe"));
            string realExe = Path.GetFullPath(proc.MainModule?.FileName ?? "");
            if (!string.Equals(realExe, expectedExe, StringComparison.OrdinalIgnoreCase)
                || proc.StartTime.ToUniversalTime().Ticks.ToString() != pidAndStart[1])
                throw new InvalidOperationException("Prozessidentität stimmt nicht überein. Keine fremden Prozesse werden beendet.");
            log.Report("Eigener RoyalDownloader-Server wird beendet …");
            proc.Kill(entireProcessTree: true);
            if (!proc.WaitForExit(15000))
                throw new InvalidOperationException("RoyalDownloader konnte nicht angehalten werden.");
        }
        catch (ArgumentException) { /* The recorded process has already exited. */ }
        catch (InvalidOperationException) { throw; }
        catch (Exception ex) { throw new InvalidOperationException(
            "Eigener Royal-Prozess konnte nicht sicher verifiziert werden; bitte zuerst beenden.", ex); }
        File.Delete(identity);
    }

    internal static void RememberOwnedServer(string root, Process process)
    {
        string data = process.Id + "|" + process.StartTime.ToUniversalTime().Ticks;
        File.WriteAllText(Path.Combine(root, "royal-server.pid"), data, Encoding.ASCII);
    }

    private static async Task<int> RunTool(string exe, string root, IEnumerable<string> args,
        IProgress<string> log, CancellationToken cancel)
    {
        var info = new ProcessStartInfo(exe)
        {
            WorkingDirectory = root, UseShellExecute = false,
            RedirectStandardOutput = true, RedirectStandardError = true,
            CreateNoWindow = true
        };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        info.Environment["UV_PYTHON_INSTALL_DIR"] = Path.Combine(root, ".python");
        info.Environment["UV_CACHE_DIR"] = Path.Combine(root, ".cache");
        info.Environment["UV_PYTHON_PREFERENCE"] = "only-managed";
        info.Environment["UV_NO_MODIFY_PATH"] = "1";
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Das Installationswerkzeug konnte nicht gestartet werden.");
        using var time = CancellationTokenSource.CreateLinkedTokenSource(cancel);
        time.CancelAfter(TimeSpan.FromMinutes(40));
        Task logOne = ReadLines(process.StandardOutput, log, time.Token);
        Task logTwo = ReadLines(process.StandardError, log, time.Token);
        try { await process.WaitForExitAsync(time.Token); }
        catch { if (!process.HasExited) process.Kill(entireProcessTree: true); throw; }
        await Task.WhenAll(logOne, logTwo);
        return process.ExitCode;
    }

    private static async Task ReadLines(StreamReader stream, IProgress<string> log, CancellationToken cancel)
    {
        while (await stream.ReadLineAsync(cancel) is { } line)
            log.Report(line.Length > 1000 ? line[..1000] : line);
    }

    private static async Task SyncPython(string root, IProgress<string> log, CancellationToken cancel)
    {
        string toolPath = Path.Combine(root, ".tools", "uv.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(toolPath)!);
        if (!File.Exists(toolPath))
            await File.WriteAllBytesAsync(toolPath, InstallerEngine.Resource("BundledUv.exe"), cancel);
        string venvPython = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!File.Exists(venvPython))
        {
            log.Report("Private Laufzeit wird wiederhergestellt …");
            if (await RunTool(toolPath, root,
                ["venv", ".venv", "--python", "3.12", "--python-preference", "only-managed"], log, cancel) != 0)
                throw new InvalidOperationException("Die private Python-Laufzeit konnte nicht wiederhergestellt werden.");
        }
        log.Report("Abhängigkeiten aus requirements.lock werden verifiziert und synchronisiert …");
        if (await RunTool(toolPath, root,
            ["pip", "sync", "--python", venvPython, "requirements.lock"], log, cancel) != 0)
            throw new InvalidOperationException("Ein Serverpaket ließ sich nicht reparieren.");
    }

    private static async Task ExtractVerified(string stage, CancellationToken cancel)
    {
        InstallerEngine.VerifyResources();
        using var memory = new MemoryStream(InstallerEngine.Resource("RoyalSource.zip"));
        using var archive = new ZipArchive(memory);
        if (archive.Entries.Count > 25000 ||
            archive.Entries.Sum(e => e.Length) > 1_500_000_000)
            throw new InvalidDataException("Quellarchiv ist zu groß.");
        string canonical = Path.GetFullPath(stage) + Path.DirectorySeparatorChar;
        var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in archive.Entries)
        {
            cancel.ThrowIfCancellationRequested();
            string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
            if (Path.IsPathRooted(relative) || relative.Split(Path.DirectorySeparatorChar)
                .Any(p => p is ".." or ".") || relative.Contains(':') ||
                ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                throw new InvalidDataException("Unsicherer Archivpfad.");
            string target = Path.GetFullPath(Path.Combine(stage, relative));
            if (!target.StartsWith(canonical, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Archivausbruch verhindert.");
            if (entry.FullName.EndsWith('/')) { Directory.CreateDirectory(target); continue; }
            if (!known.Add(target)) throw new InvalidDataException("Doppelter Archivpfad.");
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            await using var outFile = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            using var inFile = entry.Open();
            await inFile.CopyToAsync(outFile, cancel);
        }
    }

    private static void MovePersistent(string src, string dest)
    {
        foreach (string name in Retained)
        {
            string from = Path.Combine(src, name), to = Path.Combine(dest, name);
            if (File.Exists(from) && !File.Exists(to))
                File.Move(from, to);
            else if (Directory.Exists(from) && !Directory.Exists(to))
                Directory.Move(from, to);
            else if (File.Exists(from) || Directory.Exists(from))
                throw new InvalidOperationException("Ein persistenter Pfad kollidiert beim Wechsel: " + name);
        }
    }

    internal static async Task<InstallResult> ManageWindowsAsync(WindowsOptions options,
        ManagerAction operation, IProgress<string> log, CancellationToken cancel)
    {
        if (operation == ManagerAction.Install)
            return await InstallerEngine.InstallWindowsAsync(options, log, cancel);
        _ = CheckManagedWindows(options, operation);
        string root = Path.GetFullPath(options.Project);
        StopOwnedServer(root, log);
        RequireFreePort();
        if (operation == ManagerAction.Uninstall)
        {
            string safeArchive = ArchiveName(root, "deinstalliert-daten-gesichert");
            Directory.Move(root, safeArchive);
            log.Report("RoyalDownloader ist nicht mehr aktiv. Sicherung: " + safeArchive);
            return new InstallResult("", "", safeArchive);
        }
        if (operation == ManagerAction.Repair)
        {
            await SyncPython(root, log, cancel);
            await StartOwnedServer(root, log, cancel);
            log.Report("Private Abhängigkeiten repariert. Persönliche Daten und App-Dateien unverändert.");
            return new InstallResult("http://127.0.0.1:8765", "", root);
        }

        string stage = ArchiveName(root, "manager-update-stage");
        string backup = ArchiveName(root, "manager-update-backup");
        bool swapped = false;
        bool oldRenamed = false;
        try
        {
            cancel.ThrowIfCancellationRequested();
            log.Report("Das SHA-256-verifizierte Quellarchiv dieses Installers wird benutzt.");
            Directory.CreateDirectory(stage);
            await ExtractVerified(stage, cancel);
            Directory.CreateDirectory(Path.Combine(stage, ".tools"));
            await File.WriteAllBytesAsync(Path.Combine(stage, ".tools", "uv.exe"),
                InstallerEngine.Resource("BundledUv.exe"), cancel);
            string oldEnv = Path.Combine(root, ".env");
            File.Copy(oldEnv, Path.Combine(stage, ".env"));
            cancel.ThrowIfCancellationRequested();
            log.Report("Version geprüft. Programm wird atomar gewechselt; Daten bleiben erhalten …");
            Directory.Move(root, backup);
            oldRenamed = true;
            Directory.Move(stage, root);
            swapped = true;
            MovePersistent(backup, root);
            SaveMarker(root, "windows");
            // Python virtual environments must be created at their final path;
            // moving a prepared .venv from a staging folder breaks Windows script paths.
            await SyncPython(root, log, cancel);
            await StartOwnedServer(root, log, cancel);
            log.Report("Update abgeschlossen. Vorige Version zur Wiederherstellung: " + backup);
            return new InstallResult("http://127.0.0.1:8765", "", root);
        }
        catch
        {
            if (swapped)
            {
                try
                {
                    try { StopOwnedServer(root, log); } catch (Exception stopError) {
                        log.Report("Neuer Server konnte nicht automatisch beendet werden: " + stopError.Message);
                        throw;
                    }
                    MovePersistent(root, backup);
                    Directory.Move(root, ArchiveName(root, "fehlgeschlagen"));
                    Directory.Move(backup, root);
                    await StartOwnedServer(root, log, CancellationToken.None);
                }
                catch (Exception ex) { log.Report("Automatisches Rollback benötigt Prüfung: " + ex.Message); }
            }
            else if (oldRenamed)
                Directory.Move(backup, root);
            throw;
        }
        finally
        {
            // Do not auto-delete unknown contents or backup data after failure.
            if (Directory.Exists(stage))
                log.Report("Nicht verwendeter vorbereiteter Ordner bleibt zur Diagnose: " + stage);
        }
    }

    internal static void SelfTest()
    {
        var json = CreateMarker("windows");
        using var obj = JsonDocument.Parse(json);
        if (obj.RootElement.GetProperty("owner").GetString() != Owner ||
            obj.RootElement.GetProperty("platform").GetString() != "windows")
            throw new Exception("Manager marker test failed");
        if (!ArchiveName(Path.Combine(Path.GetTempPath(), "royal-test"), "backup").Contains(".backup-"))
            throw new Exception("Backup path test failed");
    }
}