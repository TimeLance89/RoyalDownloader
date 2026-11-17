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

        var window = new MainWindow();
        MainWindow = window;
        window.Show();
    }
}