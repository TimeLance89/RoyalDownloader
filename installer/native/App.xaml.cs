using System.IO;
using System.Windows;

namespace RoyalDownloader.Setup.Native;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
        {
            int result = InstallerEngine.SelfTest();
            Shutdown(result);
            return;
        }

        if (e.Args.Contains("--stable-source-test", StringComparer.OrdinalIgnoreCase))
        {
            // CI integration test: real latest published release, pinned source,
            // and normalised Windows/NAS archives; no installation side effects.
            try
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
                var package = Task.Run(async () => await StableSource.FetchLatestAsync(
                    new Progress<string>(_ => {}), timeout.Token), timeout.Token)
                    .GetAwaiter().GetResult();
                if (package.Zip.Length == 0 || package.Tar.Length == 0)
                    throw new InvalidDataException("Stable archive is empty.");
                Shutdown(0);
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(Path.GetTempPath(),
                    "royal-stable-source-test-error.txt"), error.ToString());
                Shutdown(1);
            }
            return;
        }

        var window = new MainWindow();
        MainWindow = window;
        window.Show();
    }
}