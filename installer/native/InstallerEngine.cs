using System.Diagnostics;
using System.Net.Http;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace RoyalDownloader.Setup.Native;

internal sealed record InstallResult(string Url, string Token, string InstalledAt);

internal sealed record WindowsOptions(string Project, string Movies, string Series);
internal sealed record NasOptions(string Host, int Port, string Username, string Password,
    string Project, string Movies, string Series, string PinnedFingerprint);

internal static class InstallerEngine
{
    private const string SourceZip = "RoyalSource.zip";
    private const string SourceTar = "RoyalSource.tar.gz";
    private const string UvBinary = "BundledUv.exe";
    private const string EnvTemplate = "EnvTemplate";
    private const string Manifest = "SourceManifest";
    private const int MaxExtractedFiles = 25000;
    private const long MaxExtractedBytes = 1_500_000_000;

    public static byte[] Resource(string name)
    {
        using Stream? stream = typeof(InstallerEngine).Assembly.GetManifestResourceStream(name);
        if (stream is null)
            throw new InvalidOperationException("Installer-Paket ist unvollständig: " + name);
        using var output = new MemoryStream();
        stream.CopyTo(output);
        return output.ToArray();
    }

    public static void VerifyResources()
    {
        using var manifest = JsonDocument.Parse(Resource(Manifest));
        string commit = manifest.RootElement.GetProperty("commit").GetString() ?? "";
        if (!Regex.IsMatch(commit, "^[a-f0-9]{40}$"))
            throw new InvalidDataException("Quellversion im Installer ist ungültig.");
        foreach (var item in new[]
        {
            (SourceZip, "sha256_zip"), (SourceTar, "sha256_tar"), (UvBinary, "sha256_uv")
        })
        {
            byte[] bytes = Resource(item.Item1);
            string expected = manifest.RootElement.GetProperty(item.Item2).GetString() ?? "";
            string actual = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            if (!Regex.IsMatch(expected, "^[a-f0-9]{64}$") ||
                !CryptographicOperations.FixedTimeEquals(
                    Encoding.ASCII.GetBytes(actual), Encoding.ASCII.GetBytes(expected)))
                throw new InvalidDataException("Prüfsumme stimmt nicht: " + item.Item1);
        }
        _ = Resource(EnvTemplate);
    }

    public static int SelfTest()
    {
        try
        {
            VerifyResources();
            ManagerEngine.SelfTest();
            ValidateWindows(new WindowsOptions(
                Path.Combine(Path.GetTempPath(), "royal-selftest-" + Guid.NewGuid().ToString("N")),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "RoyalTestFilme"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "RoyalTestSerien")));
            ValidateNas(new NasOptions("192.168.1.4", 22, "royal", "unused",
                "/volume1/docker/RoyalDownloader-Easy", "/volume1/media/Filme",
                "/volume1/media/Serien", "SHA256:" + new string('x', 43)), false);
            bool rejected = false;
            try
            {
                ValidateNas(new NasOptions("192.168.1.4", 22, "royal", "unused",
                    "/volume1/media", "/volume1/media/Filme",
                    "/volume1/media/Serien", "SHA256:" + new string('x', 43)), false);
            }
            catch (InvalidOperationException) { rejected = true; }
            if (!rejected) throw new Exception("Overlapping NAS directory validation failed");
            // This checks the package and path guards only; it must not modify any NAS.
            return 0;
        }
        catch (Exception error)
        {
            File.WriteAllText(Path.Combine(Path.GetTempPath(), "royal-installer-selftest-error.txt"),
                error.ToString());
            return 1;
        }
    }

    private static string TrimPath(string path)
    {
        string full = Path.GetFullPath(path.Trim());
        return Path.TrimEndingDirectorySeparator(full);
    }

    private static bool Overlaps(string a, string b, char separator)
    {
        string x = a.TrimEnd(separator), y = b.TrimEnd(separator);
        return x.Equals(y, StringComparison.OrdinalIgnoreCase) ||
            x.StartsWith(y + separator, StringComparison.OrdinalIgnoreCase) ||
            y.StartsWith(x + separator, StringComparison.OrdinalIgnoreCase);
    }

    public static void ValidateWindows(WindowsOptions options)
    {
        foreach (var item in new[] { options.Project, options.Movies, options.Series })
        {
            if (string.IsNullOrWhiteSpace(item) || !Path.IsPathFullyQualified(item))
                throw new InvalidOperationException("Bitte für alle Windows-Ordner vollständige absolute Pfade auswählen.");
            string full = TrimPath(item);
            if (Path.GetPathRoot(full)!.TrimEnd(Path.DirectorySeparatorChar)
                .Equals(full, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Ein gesamtes Laufwerk ist kein zulässiger Installationsordner.");
        }
        string project = TrimPath(options.Project);
        if (Directory.Exists(project) || File.Exists(project))
            throw new InvalidOperationException("Der Programmordner existiert schon. Bestehende Installationen bleiben unverändert.");
        string movies = TrimPath(options.Movies);
        string series = TrimPath(options.Series);
        if (Overlaps(project, movies, Path.DirectorySeparatorChar) ||
            Overlaps(project, series, Path.DirectorySeparatorChar))
            throw new InvalidOperationException("Programmordner und Medienordner dürfen sich nicht überschneiden.");
    }

    private static readonly Regex SafeHost = new(
        "^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$", RegexOptions.Compiled);
    private static readonly Regex SafeUsername = new(
        "^[a-zA-Z_][a-zA-Z0-9_.-]{0,62}$", RegexOptions.Compiled);
    private static readonly Regex SafeRemotePath = new(
        "^/[a-zA-Z0-9_./ -]+$", RegexOptions.Compiled);

    public static void ValidateNas(NasOptions options, bool requirePin = true)
    {
        if (!SafeHost.IsMatch(options.Host) || !SafeUsername.IsMatch(options.Username) ||
            options.Port < 1 || options.Port > 65535)
            throw new InvalidOperationException("NAS-Adresse, Port oder SSH-Benutzer sind ungültig.");
        if (string.IsNullOrWhiteSpace(options.Password))
            throw new InvalidOperationException("Bitte das SSH-Passwort eingeben.");
        var paths = new[] { options.Project, options.Movies, options.Series };
        foreach (var path in paths)
        {
            if (!SafeRemotePath.IsMatch(path) || path.Contains("//") ||
                path.Split('/').Any(segment => segment is "." or "..") ||
                path.EndsWith('/') || path is "/" or "/root" or "/etc" or "/usr" or "/var" or "/home")
                throw new InvalidOperationException("NAS-Pfade müssen vollständige, sichere Linux-Pfade sein.");
        }
        if (Overlaps(options.Project, options.Movies, '/') ||
            Overlaps(options.Project, options.Series, '/'))
            throw new InvalidOperationException("Der NAS-Projektordner darf sich nicht mit Medienordnern überschneiden.");
        if (requirePin && !Regex.IsMatch(options.PinnedFingerprint, @"^SHA256:[A-Za-z0-9+/]{43}$"))
            throw new InvalidOperationException("Ein bestätigter SSH-Hostschlüssel fehlt.");
    }

    public static string NewToken() =>
        "RD-" + Convert.ToBase64String(RandomNumberGenerator.GetBytes(24))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static string EnvEscape(string s)
    {
        if (s.IndexOfAny(['\r', '\n', '\0', '#', '$', '\'', '"']) >= 0)
            throw new InvalidOperationException("Ein Installationspfad enthält nicht zulässige Sonderzeichen.");
        return s;
    }

    public static string RenderEnv(Dictionary<string, string> values)
    {
        string template = Encoding.UTF8.GetString(Resource(EnvTemplate));
        var remaining = new Dictionary<string, string>(values);
        var output = new StringBuilder();
        foreach (string line in template.Split('\n'))
        {
            string clean = line.TrimEnd('\r');
            string key = clean.Split('=', 2)[0];
            if (remaining.TryGetValue(key, out string? value))
            {
                output.Append(key).Append('=').Append(EnvEscape(value)).Append('\n');
                remaining.Remove(key);
            }
            else if (clean.Length > 0)
                output.Append(clean).Append('\n');
        }
        foreach (var (key, value) in remaining.OrderBy(item => item.Key))
            output.Append(key).Append('=').Append(EnvEscape(value)).Append('\n');
        return output.ToString();
    }

    private static Dictionary<string, string> BaseEnv(string token) => new()
    {
        ["ROYAL_SETUP_TOKEN"] = token,
        ["SEERR_ENABLED"] = "false",
        ["UPDATE_CHANNEL"] = "stable",
        ["UPDATE_GITHUB_BRANCH"] = "main",
        ["UPDATE_MODE"] = "manual",
        ["JELLYFIN_URL"] = "",
        ["JELLYFIN_API_KEY"] = ""
    };

    private static async Task ExtractSourceAsync(string directory, CancellationToken cancel)
    {
        var zipBytes = Resource(SourceZip);
        using var ms = new MemoryStream(zipBytes);
        using var zip = new ZipArchive(ms, ZipArchiveMode.Read, leaveOpen: false);
        if (zip.Entries.Count > MaxExtractedFiles ||
            zip.Entries.Sum(item => item.Length) > MaxExtractedBytes)
            throw new InvalidDataException("Quellarchiv überschreitet die sichere Obergrenze.");
        string root = Path.GetFullPath(directory) + Path.DirectorySeparatorChar;
        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in zip.Entries)
        {
            cancel.ThrowIfCancellationRequested();
            string logical = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
            if (logical.StartsWith(Path.DirectorySeparatorChar) ||
                logical.Split(Path.DirectorySeparatorChar).Any(part => part == "..") ||
                logical.Contains(':') || logical.Contains('\0'))
                throw new InvalidDataException("Unsicherer Quellarchivpfad.");
            string full = Path.GetFullPath(Path.Combine(directory, logical));
            if (!full.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Quellarchiv greift außerhalb des Projektordners zu.");
            // Git ZIP symbolic links are rejected instead of being materialized as text files.
            if (((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                throw new InvalidDataException("Verlinkte Dateien im Quellarchiv sind nicht erlaubt.");
            if (entry.FullName.EndsWith('/'))
            {
                Directory.CreateDirectory(full);
                continue;
            }
            if (!visited.Add(full))
                throw new InvalidDataException("Doppelter Dateipfad im Quellarchiv.");
            Directory.CreateDirectory(Path.GetDirectoryName(full)!);
            using var input = entry.Open();
            await using var output = new FileStream(full, FileMode.CreateNew,
                FileAccess.Write, FileShare.None, 81920, useAsync: true);
            await input.CopyToAsync(output, cancel);
        }
    }

    private static async Task<int> RunAsync(
        string command, IEnumerable<string> arguments, string workingDirectory,
        IDictionary<string, string>? environment, IProgress<string> log,
        CancellationToken cancel, int minutes = 20)
    {
        var info = new ProcessStartInfo(command)
        {
            WorkingDirectory = workingDirectory, UseShellExecute = false,
            RedirectStandardError = true, RedirectStandardOutput = true,
            CreateNoWindow = true
        };
        foreach (string arg in arguments) info.ArgumentList.Add(arg);
        if (environment is not null)
            foreach (var (key, value) in environment) info.Environment[key] = value;

        using var proc = new Process { StartInfo = info };
        proc.Start();
        Task stdout = PumpAsync(proc.StandardOutput, log, cancel);
        Task stderr = PumpAsync(proc.StandardError, log, cancel);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancel);
        timeout.CancelAfter(TimeSpan.FromMinutes(minutes));
        try { await proc.WaitForExitAsync(timeout.Token); }
        catch
        {
            if (!proc.HasExited) proc.Kill(entireProcessTree: true);
            throw;
        }
        await Task.WhenAll(stdout, stderr);
        return proc.ExitCode;
    }

    private static async Task PumpAsync(StreamReader reader, IProgress<string> log,
        CancellationToken cancellation)
    {
        while (await reader.ReadLineAsync(cancellation) is { } line)
        {
            if (line.Length > 2000) line = line[..2000];
            log.Report(line);
        }
    }

    public static string WindowsPreflight(WindowsOptions config)
    {
        ValidateWindows(config);
        var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(config.Project))!);
        if (drive.AvailableFreeSpace < 2L * 1024 * 1024 * 1024)
            throw new InvalidOperationException("Auf dem Installationslaufwerk müssen mindestens 2 GiB frei sein.");
        VerifyResources();
        return "Paketprüfung erfolgreich · Private Laufzeit wird nur im Royal-Ordner erstellt · " +
               "Keine globale Python-Installation · Keine vorhandenen Verzeichnisse werden überschrieben.";
    }

    public static async Task<InstallResult> InstallWindowsAsync(WindowsOptions config,
        IProgress<string> log, CancellationToken cancel)
    {
        WindowsPreflight(config);
        string destination = Path.GetFullPath(config.Project);
        string staging = destination + ".stage-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(6)).ToLowerInvariant();
        string token = NewToken();
        bool committed = false;
        try
        {
            log.Report("Verifiziertes RoyalDownloader-Paket wird vorbereitet …");
            Directory.CreateDirectory(staging);
            await ExtractSourceAsync(staging, cancel);
            Directory.CreateDirectory(Path.Combine(staging, "data"));
            Directory.CreateDirectory(Path.Combine(staging, "runtime"));
            var env = BaseEnv(token);
            env["ROYAL_DEPLOYMENT_MODE"] = "desktop";
            env["HOST"] = "127.0.0.1";
            env["ROYAL_BIND_ADDRESS"] = "127.0.0.1";
            env["OPEN_BROWSER"] = "0";
            env["DNS_OVERRIDE"] = "0";
            env["DOWNLOAD_DIR"] = config.Movies;
            env["SERIES_DIR"] = config.Series;
            env["MOVIES_HOST_DIR"] = config.Movies;
            env["SERIES_HOST_DIR"] = config.Series;
            await File.WriteAllTextAsync(Path.Combine(staging, ".env"),
                RenderEnv(env), Encoding.UTF8, cancel);
            Directory.CreateDirectory(Path.Combine(staging, ".tools"));
            await File.WriteAllBytesAsync(Path.Combine(staging, ".tools", "uv.exe"),
                Resource(UvBinary), cancel);
            if (Directory.Exists(destination) || File.Exists(destination))
                throw new InvalidOperationException("Zwischenzeitlich wurde der Zielordner angelegt – Vorgang abgebrochen.");
            Directory.Move(staging, destination);
            committed = true;
            ManagerEngine.SaveMarker(destination, "windows");

            // uv downloads an isolated, managed interpreter into this application's own folder.
            // Never install, discover, replace or alter system Python.
            log.Report("Private Python-Laufzeit für RoyalDownloader wird eingerichtet …");
            string uv = Path.Combine(destination, ".tools", "uv.exe");
            var environment = new Dictionary<string, string>
            {
                ["UV_PYTHON_INSTALL_DIR"] = Path.Combine(destination, ".python"),
                ["UV_CACHE_DIR"] = Path.Combine(destination, ".cache"),
                ["UV_PYTHON_PREFERENCE"] = "only-managed",
                ["UV_NO_MODIFY_PATH"] = "1"
            };
            int exit = await RunAsync(uv,
                ["venv", ".venv", "--python", "3.12", "--python-preference", "only-managed"],
                destination, environment, log, cancel);
            if (exit != 0) throw new InvalidOperationException("Private Python-Laufzeit konnte nicht eingerichtet werden.");

            log.Report("RoyalDownloader-Serverpakete werden isoliert installiert …");
            string py = Path.Combine(destination, ".venv", "Scripts", "python.exe");
            exit = await RunAsync(uv,
                ["pip", "sync", "--python", py, "requirements.lock"],
                destination, environment, log, cancel, 35);
            if (exit != 0) throw new InvalidOperationException(
                "Ein Serverpaket konnte nicht eingerichtet werden. Das eigene Python wurde nicht verändert.");

            Directory.CreateDirectory(config.Movies);
            Directory.CreateDirectory(config.Series);
            string launcher = "@echo off\r\ncd /d \"%~dp0\"\r\n\"%~dp0.venv\\Scripts\\python.exe\" \"%~dp0server.py\"\r\n";
            await File.WriteAllTextAsync(Path.Combine(destination, "RoyalDownloader starten.cmd"),
                launcher, Encoding.ASCII, cancel);
            log.Report("RoyalDownloader wurde lokal installiert. Starte den Dienst …");

            var serverInfo = new ProcessStartInfo(py)
            {
                WorkingDirectory = destination, UseShellExecute = false,
                CreateNoWindow = true
            };
            serverInfo.ArgumentList.Add(Path.Combine(destination, "server.py"));
            using var ownedServer = Process.Start(serverInfo) ?? throw new InvalidOperationException(
                "RoyalDownloader konnte nicht gestartet werden.");
            ManagerEngine.RememberOwnedServer(destination, ownedServer);
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
            bool healthy = false;
            for (int attempt = 0; attempt < 30; attempt++)
            {
                cancel.ThrowIfCancellationRequested();
                await Task.Delay(1000, cancel);
                try
                {
                    using var response = await client.GetAsync("http://127.0.0.1:8765/api/health", cancel);
                    if (response.IsSuccessStatusCode) { healthy = true; break; }
                }
                catch (HttpRequestException) { }
                catch (TaskCanceledException) when (!cancel.IsCancellationRequested) { }
            }
            if (!healthy) throw new InvalidOperationException(
                "RoyalDownloader ist installiert, meldet aber noch keinen erfolgreichen Gesundheitscheck.");
            return new InstallResult("http://127.0.0.1:8765", token, destination);
        }
        catch (Exception error)
        {
            if (!committed && Directory.Exists(staging))
            {
                try { Directory.Delete(staging, true); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            throw new InvalidOperationException(error.Message +
                (committed ? " Der neue Royal-Ordner bleibt für die Fehlerdiagnose erhalten; bestehende Installationen wurden nicht verändert." : ""), error);
        }
    }
}