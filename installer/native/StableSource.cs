using System.Formats.Tar;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace RoyalDownloader.Setup.Native;

internal sealed record StableRelease(string Version, string Commit);
internal sealed record StablePackage(string Version, string Commit, byte[] Zip, byte[] Tar);

/// <summary>
/// Always resolves the latest published, non-prerelease GitHub release.
/// Archive URLs are pinned to the resolved immutable commit SHA. No silently
/// stale embedded source is used for install or update when GitHub is offline.
/// </summary>
internal static class StableSource
{
    private const string RepoApi = "https://api.github.com/repos/TimeLance89/RoyalDownloader";
    private const int MaxCompressedBytes = 100 * 1024 * 1024;
    private const long MaxExpandedBytes = 1_500_000_000;
    private const int MaxEntries = 25000;
    private static readonly Regex ShaPattern = new("^[a-f0-9]{40}$", RegexOptions.Compiled);
    private static readonly Regex TagPattern = new("^v[0-9]+\\.[0-9]+\\.[0-9]+$", RegexOptions.Compiled);
    private static readonly HttpClient Http = CreateHttp();

    private static HttpClient CreateHttp()
    {
        var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = true })
        { Timeout = TimeSpan.FromMinutes(3) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("RoyalDownloader-Installationsmanager/1.1");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        return client;
    }

    private static async Task<byte[]> DownloadAsync(string uri, CancellationToken cancel, int maxBytes = MaxCompressedBytes)
    {
        using var response = await Http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancel);
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException(
                "GitHub Stable ist nicht erreichbar (HTTP " + (int)response.StatusCode +
                "). Keine ältere Version wird ersatzweise installiert.");
        if (response.Content.Headers.ContentLength is long length && length > maxBytes)
            throw new InvalidDataException("GitHub-Download überschreitet die maximale Paketgröße.");
        await using var stream = await response.Content.ReadAsStreamAsync(cancel);
        using var buffer = new MemoryStream();
        byte[] chunk = new byte[65536];
        int count;
        while ((count = await stream.ReadAsync(chunk, cancel)) != 0)
        {
            if (buffer.Length + count > maxBytes)
                throw new InvalidDataException("GitHub-Download überschreitet die maximale Paketgröße.");
            buffer.Write(chunk, 0, count);
        }
        return buffer.ToArray();
    }

    private static JsonElement ReadObject(byte[] bytes)
    {
        using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions
        {
            MaxDepth = 16,
        });
        if (document.RootElement.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("GitHub hat kein gültiges Release-Dokument geliefert.");
        return document.RootElement.Clone();
    }

    internal static async Task<StableRelease> LookupLatestAsync(CancellationToken cancellation)
    {
        try
        {
            var release = ReadObject(await DownloadAsync(RepoApi + "/releases/latest", cancellation, 1024 * 1024));
            string tag = release.GetProperty("tag_name").GetString() ?? "";
            if (!TagPattern.IsMatch(tag) ||
                release.GetProperty("draft").GetBoolean() ||
                release.GetProperty("prerelease").GetBoolean())
                throw new InvalidDataException("Die neueste Veröffentlichung ist kein reguläres Stable-Release.");

            // Resolve release tag, including annotated tags, to an exact commit.
            // Do not use main HEAD: it can be newer than the last stable release.
            var reference = ReadObject(await DownloadAsync(
                RepoApi + "/git/ref/tags/" + tag, cancellation, 1024 * 1024));
            var target = reference.GetProperty("object");
            string kind = target.GetProperty("type").GetString() ?? "";
            string sha = target.GetProperty("sha").GetString() ?? "";
            for (int depth = 0; kind == "tag" && depth < 4; depth++)
            {
                if (!ShaPattern.IsMatch(sha))
                    throw new InvalidDataException("Ungültiger Git-Tag-Hash.");
                var annotated = ReadObject(await DownloadAsync(
                    RepoApi + "/git/tags/" + sha, cancellation, 1024 * 1024));
                target = annotated.GetProperty("object");
                kind = target.GetProperty("type").GetString() ?? "";
                sha = target.GetProperty("sha").GetString() ?? "";
            }
            if (kind != "commit" || !ShaPattern.IsMatch(sha))
                throw new InvalidDataException("Stable-Tag konnte keinem eindeutigen Git-Commit zugeordnet werden.");

            return new StableRelease(tag, sha);
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception error)
        {
            throw new InvalidOperationException(
                "Die aktuellste Stable-Version konnte nicht verifiziert werden. " +
                "Zur Sicherheit wird kein alter, eingebauter Quellstand verwendet. " + error.Message, error);
        }
    }

    internal static async Task<StablePackage> FetchLatestAsync(
        IProgress<string> progress, CancellationToken cancellation)
    {
        StableRelease release = await LookupLatestAsync(cancellation);
        progress.Report("Neueste Stable: " + release.Version + " · Commit " + release.Commit[..12]);
        progress.Report("Lade den exakt zu diesem Commit gehörenden Quellstand von GitHub …");
        byte[] original = await DownloadAsync(RepoApi + "/zipball/" + release.Commit, cancellation);
        var (zip, tar) = NormalizeGitHubZip(original, cancellation);
        progress.Report("Stable-Archiv geprüft: " + release.Version + " · " +
            Convert.ToHexString(SHA256.HashData(zip)).ToLowerInvariant()[..16] + "… (SHA-256)");
        return new StablePackage(release.Version, release.Commit, zip, tar);
    }

    /// <summary>
    /// GitHub archives have a generated outer directory. Remove that directory
    /// and normalize into the same checked ZIP/TAR formats used by the installer.
    /// ZIP/TAR contents are derived from precisely the same pinned bytes.
    /// </summary>
    internal static (byte[] Zip, byte[] Tar) NormalizeGitHubZip(
        byte[] sourceBytes, CancellationToken cancellation)
    {
        using var input = new ZipArchive(new MemoryStream(sourceBytes), ZipArchiveMode.Read);
        if (input.Entries.Count is 0 or > MaxEntries)
            throw new InvalidDataException("GitHub-Archiv ist leer oder enthält zu viele Dateien.");
        var validFiles = input.Entries.Where(e => !e.FullName.EndsWith('/')).ToArray();
        if (validFiles.Length == 0 || validFiles.Sum(e => e.Length) > MaxExpandedBytes)
            throw new InvalidDataException("Quellarchiv überschreitet die sichere Obergrenze.");
        string prefix = input.Entries[0].FullName.Split('/')[0] + "/";
        if (prefix.Length < 3 || !prefix.EndsWith('/'))
            throw new InvalidDataException("GitHub-Archiv hat keinen gültigen Paketordner.");

        using var zipBuffer = new MemoryStream();
        using var tarBuffer = new MemoryStream();
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using (var outputZip = new ZipArchive(zipBuffer, ZipArchiveMode.Create, true))
        using (var gzip = new GZipStream(tarBuffer, CompressionLevel.Fastest, leaveOpen: true))
        using (var tarWriter = new TarWriter(gzip, leaveOpen: true))
        {
            foreach (var entry in validFiles)
            {
                cancellation.ThrowIfCancellationRequested();
                if (!entry.FullName.StartsWith(prefix, StringComparison.Ordinal) ||
                    entry.FullName.Contains('\\') ||
                    ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                    throw new InvalidDataException("Unsicherer GitHub-Archivpfad.");

                string path = entry.FullName[prefix.Length..];
                if (path.Length == 0 || path.StartsWith('/') || path.Contains(':') ||
                    path.Contains('\0') || path.Split('/').Any(part => part is "." or ".." or ""))
                    throw new InvalidDataException("Ungültiger Paketpfad: " + path);
                if (!paths.Add(path))
                    throw new InvalidDataException("GitHub-Archiv enthält doppelte Pfade.");

                var dest = outputZip.CreateEntry(path, CompressionLevel.Fastest);
                using (var reader = entry.Open())
                using (var writer = dest.Open())
                    reader.CopyTo(writer);
                using var tarStream = entry.Open();
                var tarEntry = new PaxTarEntry(TarEntryType.RegularFile, path)
                { DataStream = tarStream };
                tarWriter.WriteEntry(tarEntry);
            }
        }

        foreach (string required in new[] { ".env.example", "server.py", "requirements.lock", "docker-compose.yml" })
            if (!paths.Contains(required))
                throw new InvalidDataException("Das Stable-Archiv enthält eine erforderliche Datei nicht: " + required);

        return (zipBuffer.ToArray(), tarBuffer.ToArray());
    }

    internal static void SelfTest()
    {
        using var sample = new MemoryStream();
        using (var zip = new ZipArchive(sample, ZipArchiveMode.Create, leaveOpen: true))
            foreach (var path in new[] { ".env.example", "server.py", "requirements.lock", "docker-compose.yml" })
            {
                using var stream = zip.CreateEntry("repo-abc123/" + path).Open();
                stream.WriteByte(49);
            }
        var (normalized, tar) = NormalizeGitHubZip(sample.ToArray(), CancellationToken.None);
        using var result = new ZipArchive(new MemoryStream(normalized), ZipArchiveMode.Read);
        if (result.GetEntry("server.py") is null || result.GetEntry("repo-abc123/server.py") is not null || tar.Length < 50)
            throw new Exception("Stable source normalization self-test failed.");
    }
}