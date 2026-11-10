using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace RoyalDownloader.Setup.Native;

public partial class MainWindow : Window
{
    private static readonly string[] Titles =
    [
        "RoyalDownloader verwalten",
        "Sichere Verbindung herstellen",
        "Deine Speicherorte",
        "Alles vor dem Start prüfen",
        "RoyalDownloader installieren",
        "RoyalDownloader ist bereit"
    ];

    private static readonly string[] Descriptions =
    [
        "Neu installieren, reparieren, aktualisieren oder deinstallieren – auf Windows und deinem NAS.",
        "Auf Windows ist keine globale Python-Installation erforderlich. Beim NAS prüfen wir zuerst den SSH-Hostschlüssel.",
        "Lege fest, wo Programm, Filme und Serien gespeichert werden sollen.",
        "Diese Prüfung verändert keine bestehenden Programme, Container oder Mediendateien.",
        "Die Installation beginnt erst nach deiner ausdrücklichen Bestätigung.",
        "Führe nun die Ersteinrichtung in deinem Browser zu Ende."
    ];

    private int _step;
    private bool _busy;
    private string? _probedFingerprint;
    private InstallResult? _result;
    private CancellationTokenSource? _installCancellation;

    public MainWindow()
    {
        InitializeComponent();
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        WinInstallPath.Text = Path.Combine(local, "RoyalDownloader");
        WinMoviesPath.Text = Path.Combine(home, "Videos", "RoyalDownloader", "Filme");
        WinSeriesPath.Text = Path.Combine(home, "Videos", "RoyalDownloader", "Serien");
        ShowStep(0);
    }

    private bool IsNas => MethodNas.IsChecked == true;
    private ManagerAction Operation =>
        ActionRemove.IsChecked == true ? ManagerAction.Uninstall :
        ActionUpdate.IsChecked == true ? ManagerAction.Update :
        ActionRepair.IsChecked == true ? ManagerAction.Repair :
        ManagerAction.Install;

    private void ActionChanged(object sender, RoutedEventArgs e)
    {
        if (IsLoaded) ShowStep(_step);
    }

    private void MethodChanged(object sender, RoutedEventArgs e)
    {
        if (!IsLoaded) return;
        SyncMethodPanels();
    }

    private void SyncMethodPanels()
    {
        WindowsConnect.Visibility = IsNas ? Visibility.Collapsed : Visibility.Visible;
        NasConnect.Visibility = IsNas ? Visibility.Visible : Visibility.Collapsed;
        WindowsStorage.Visibility = IsNas ? Visibility.Collapsed : Visibility.Visible;
        NasStorage.Visibility = IsNas ? Visibility.Visible : Visibility.Collapsed;
    }

    private void ShowStep(int value)
    {
        _step = Math.Clamp(value, 0, 5);
        StepTitle.Text = _step switch
        {
            0 => "Was möchtest du mit RoyalDownloader tun?",
            4 => ManagerEngine.OperationName(Operation) + " läuft",
            5 => "Vorgang abgeschlossen",
            _ => Titles[_step]
        };
        StepHint.Text = Descriptions[_step];
        StepCaption.Text = "ROYAL EASY INSTALL / " + (_step + 1).ToString("00");
        FooterStatus.Text = "SCHRITT " + (_step + 1) + " VON 6";
        foreach (var page in new[] { Page0, Page1, Page2, Page3, Page4, Page5 })
            page.Visibility = Visibility.Collapsed;
        new[] { Page0, Page1, Page2, Page3, Page4, Page5 }[_step].Visibility = Visibility.Visible;
        var rails = new[] { Rail0, Rail1, Rail2, Rail3, Rail4, Rail5 };
        for (int i = 0; i < rails.Length; i++)
        {
            rails[i].Foreground = i == _step ? Brushes.White : new SolidColorBrush(Color.FromRgb(154, 172, 201));
            rails[i].FontWeight = i == _step ? FontWeights.Bold : FontWeights.Normal;
        }
        NextButton.Content = _step switch
        {
            3 => "Voraussetzungen prüfen",
            4 => Operation == ManagerAction.Uninstall ? "Sicher deinstallieren" : ManagerEngine.OperationName(Operation) + " starten",
            5 => "Schließen",
            _ => "Weiter →"
        };
        BackButton.IsEnabled = _step > 0 && _step < 4 && !_busy;
        NextButton.IsEnabled = !_busy;
        if (_step == 1 || _step == 2) SyncMethodPanels();
    }

    private void SetBusy(bool value)
    {
        _busy = value;
        BackButton.IsEnabled = !value && _step > 0 && _step < 4;
        NextButton.IsEnabled = !value;
        ProbeHostButtonEnabled(!value);
    }

    private void ProbeHostButtonEnabled(bool value)
    {
        // No window-level SSH action remains enabled while an installation is active.
        foreach (Button button in WalkButtons(NasConnect))
            button.IsEnabled = value;
    }

    private static IEnumerable<Button> WalkButtons(DependencyObject root)
    {
        for (int i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            DependencyObject child = VisualTreeHelper.GetChild(root, i);
            if (child is Button button) yield return button;
            foreach (var nested in WalkButtons(child)) yield return nested;
        }
    }

    private WindowsOptions WindowsConfig() =>
        new(WinInstallPath.Text.Trim(), WinMoviesPath.Text.Trim(), WinSeriesPath.Text.Trim());

    private NasOptions NasConfig(bool pinRequired = true)
    {
        if (!int.TryParse(NasPort.Text.Trim(), out int port))
            throw new InvalidOperationException("Bitte einen gültigen SSH-Port eingeben.");
        var options = new NasOptions(NasHost.Text.Trim(), port, NasUser.Text.Trim(), NasPassword.Password,
            NasProject.Text.Trim(), NasMovies.Text.Trim(), NasSeries.Text.Trim(),
            _probedFingerprint ?? "");
        InstallerEngine.ValidateNas(options, pinRequired);
        return options;
    }

    private void ShowError(Exception error) =>
        MessageBox.Show(this, error.Message, "RoyalDownloader · Einrichtung", MessageBoxButton.OK,
            MessageBoxImage.Warning);

    private async void ProbeHost_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var options = NasConfig(false);
            SetBusy(true);
            HostFingerprint.Text = "Verbindung wird geprüft, noch ohne Übertragung deines Passworts …";
            string fingerprint = await Task.Run(() => NasInstaller.ProbeHostKey(options));
            _probedFingerprint = fingerprint;
            HostFingerprint.Text = "Gefundener SSH-Hostschlüssel: " + fingerprint +
                "\nVergleiche ihn unabhängig mit der NAS-Konsole, bevor du ihn bestätigst.";
            ConfirmedFingerprint.Clear();
        }
        catch (Exception error)
        {
            _probedFingerprint = null;
            HostFingerprint.Text = "Kein gültiger SSH-Hostschlüssel verfügbar.";
            ShowError(error);
        }
        finally { SetBusy(false); }
    }

    private void EnsureHostApproved()
    {
        if (string.IsNullOrWhiteSpace(_probedFingerprint) ||
            !string.Equals(ConfirmedFingerprint.Text.Trim(), _probedFingerprint,
                StringComparison.Ordinal))
            throw new InvalidOperationException(
                "Bitte den SSH-Hostschlüssel unabhängig vergleichen und den vollständigen Fingerabdruck exakt bestätigen.");
    }

    private void SetReview()
    {
        var action = Operation;
        if (IsNas)
        {
            EnsureHostApproved();
            var cfg = NasConfig();
            ReviewDescription.Text = "Vorgang: " + ManagerEngine.OperationName(action) +
                "\nNAS: " + cfg.Host + ":" + cfg.Port +
                "\nProjekt: " + cfg.Project +
                "\nFilme: " + cfg.Movies + "\nSerien: " + cfg.Series +
                "\nSSH-Hostschlüssel muss auch bei SFTP übereinstimmen. " +
                "Bestehende fremde Docker-Projekte und Mediendateien werden nicht verändert.";
        }
        else
        {
            var cfg = WindowsConfig();
            if (action == ManagerAction.Install) InstallerEngine.ValidateWindows(cfg);
            else _ = ManagerEngine.CheckManagedWindows(cfg, action);
            ReviewDescription.Text = "Vorgang: " + ManagerEngine.OperationName(action) +
                "\nWindows-PC: " + cfg.Project + "\nFilme: " + cfg.Movies + "\nSerien: " + cfg.Series +
                "\nPython wird ausschließlich privat verwaltet. " +
                "Bei Deinstallation bleiben Einstellungen und Medien als Archiv erhalten.";
        }
        ReviewResult.Text = "Noch nicht geprüft. Klicke unten auf „Voraussetzungen prüfen“.";
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _step is 0 or >= 4) return;
        ShowStep(_step - 1);
    }

    private async void Next_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        try
        {
            switch (_step)
            {
                case 0:
                    ShowStep(1);
                    break;
                case 1:
                    if (IsNas) EnsureHostApproved();
                    ShowStep(2);
                    break;
                case 2:
                    SetReview();
                    ShowStep(3);
                    break;
                case 3:
                    await PerformPreflightAsync();
                    break;
                case 4:
                    await PerformInstallAsync();
                    break;
                case 5:
                    Close();
                    break;
            }
        }
        catch (Exception error) { ShowError(error); }
    }

    private async Task PerformPreflightAsync()
    {
        SetBusy(true);
        ReviewResult.Text = "Prüfung läuft …";
        try
        {
            string result;
            if (IsNas)
            {
                EnsureHostApproved();
                var cfg = NasConfig();
                result = await Task.Run(() => NasManager.Preflight(cfg, Operation));
            }
            else
            {
                var cfg = WindowsConfig();
                result = await Task.Run(() => ManagerEngine.CheckManagedWindows(cfg, Operation));
            }
            ReviewResult.Text = "✓ " + result;
            ShowStep(4);
        }
        catch (Exception error)
        {
            ReviewResult.Text = "Prüfung nicht bestanden:\n" + error.Message;
            throw;
        }
        finally { SetBusy(false); }
    }

    private async Task PerformInstallAsync()
    {
        if (Operation == ManagerAction.Uninstall)
        {
            var place = IsNas ? NasProject.Text.Trim() : WinInstallPath.Text.Trim();
            var confirmation = MessageBox.Show(this,
                "RoyalDownloader wird im aktiven Projektordner deaktiviert.\n\n" +
                place + "\n\nEine Daten- und Programmsicherung bleibt bestehen. Externe Filme und Serien werden nie gelöscht.\n\nFortfahren?",
                "Deinstallation ausdrücklich bestätigen", MessageBoxButton.YesNo, MessageBoxImage.Warning);
            if (confirmation != MessageBoxResult.Yes) return;
        }
        SetBusy(true);
        InstallLog.Clear();
        InstallProgress.IsIndeterminate = true;
        _installCancellation = new CancellationTokenSource();
        var progress = new Progress<string>(message =>
        {
            InstallLog.AppendText(message + Environment.NewLine);
            InstallLog.ScrollToEnd();
        });
        try
        {
            if (IsNas)
            {
                EnsureHostApproved();
                var cfg = NasConfig();
                _result = await Task.Run(() => NasManager.Manage(
                    cfg, Operation, progress, _installCancellation.Token));
            }
            else
            {
                var cfg = WindowsConfig();
                _result = await ManagerEngine.ManageWindowsAsync(
                    cfg, Operation, progress, _installCancellation.Token);
            }
            FinishedUrl.Text = Operation == ManagerAction.Uninstall ? _result.InstalledAt : _result.Url;
            FinishedToken.Text = _result.Token;
            FinishedTitle.Text = "✓ " + ManagerEngine.OperationName(Operation) + " abgeschlossen.";
            FinishedUrlLabel.Text = Operation == ManagerAction.Uninstall ? "Sicherungsordner (Daten bleiben erhalten):" : "RoyalDownloader-Adresse:";
            FinishedTokenLabel.Visibility = Operation == ManagerAction.Install ? Visibility.Visible : Visibility.Collapsed;
            FinishedToken.Visibility = Operation == ManagerAction.Install ? Visibility.Visible : Visibility.Collapsed;
            OpenRoyalButton.IsEnabled = Operation != ManagerAction.Uninstall;
            ShowStep(5);
        }
        catch (Exception error)
        {
            InstallLog.AppendText("\nINSTALLATION ABGEBROCHEN:\n" + error.Message + "\n");
            ShowError(error);
        }
        finally
        {
            InstallProgress.IsIndeterminate = false;
            _installCancellation?.Dispose();
            _installCancellation = null;
            SetBusy(false);
        }
    }

    private void OpenRoyal_Click(object sender, RoutedEventArgs e)
    {
        if (_result is null || string.IsNullOrWhiteSpace(_result.Url)) return;
        try
        {
            Process.Start(new ProcessStartInfo(_result.Url) { UseShellExecute = true });
        }
        catch (Exception error) { ShowError(error); }
    }

    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        if (_busy && _step == 4)
        {
            e.Cancel = true;
            MessageBox.Show(this, "Die Installation läuft. Schließe den Installer nicht während einer Docker- oder Paketaktion.",
                "RoyalDownloader", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        base.OnClosing(e);
    }
}