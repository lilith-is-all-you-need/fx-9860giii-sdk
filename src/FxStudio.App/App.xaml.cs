using System.IO;
using System.Text.Json;
using System.Windows;

namespace FxStudio.App;

public partial class App : Application
{
    public static string DataDirectory { get; private set; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FxStudio");
    public static StudioSettings Settings { get; private set; } = new();
    public static string RootDirectory { get; private set; } = AppContext.BaseDirectory;
    public static string? LaunchGdbOverride { get; private set; }
    public static string? LaunchEmulatorOverride { get; private set; }
    public static string? LaunchSdkOverride { get; private set; }
    public static bool IsVerification { get; private set; }
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        string? Option(string name) { var index = Array.IndexOf(e.Args, name); return index >= 0 && index + 1 < e.Args.Length ? e.Args[index + 1] : null; }
        if (Option("--settings-dir") is { } settingsDirectory) DataDirectory = Path.GetFullPath(settingsDirectory);
        Directory.CreateDirectory(DataDirectory);
        try { Settings = JsonSerializer.Deserialize<StudioSettings>(File.ReadAllText(Path.Combine(DataDirectory, "settings.json"))) ?? new(); } catch (IOException) { } catch (JsonException) { }
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            if (Directory.Exists(Path.Combine(dir.FullName, "examples"))) { RootDirectory = dir.FullName; break; }
        Language.Set(Settings.Language);
        DispatcherUnhandledException += (_, a) => { MessageBox.Show(a.Exception.Message, "Fx Studio", MessageBoxButton.OK, MessageBoxImage.Error); a.Handled = true; };
        LaunchGdbOverride = Option("--gdb"); LaunchEmulatorOverride = Option("--emulator");
        LaunchSdkOverride = Option("--sdk");
        IsVerification = Option("--render-to") != null;
        if (Option("--language") is { } language) Language.Set(language);
        var project = Option("--debug-build") ?? Option("--build-and-debug") ?? Option("--project") ?? (e.Args.FirstOrDefault()?.StartsWith("--") == false ? e.Args[0] : null);
        var window = new MainWindow(project, Option("--debug-build") != null, Option("--build-and-debug") != null);
        MainWindow = window;
        if (Option("--render-to") is { } renderPath) {
            window.ContentRendered += async (_, _) => { try { await window.RenderForVerificationAsync(renderPath, Option("--render-break"), e.Args.Contains("--verify-interactions")); } catch (Exception ex) { File.WriteAllText(renderPath + ".error.txt", ex.ToString()); await window.CloseForVerificationAsync(); Shutdown(1); } };
        }
        window.Show();
    }
    public static void SaveSettings()
    {
        var path = Path.Combine(DataDirectory, "settings.json");
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(Settings, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(temporary, path, true);
    }
}

public sealed class StudioSettings
{
    public string Language { get; set; } = System.Globalization.CultureInfo.CurrentUICulture.Name.StartsWith("zh") ? "zh-CN" : "en";
    public string Distro { get; set; } = "FxSDK-Dev-20261114";
    public string EmulatorPath { get; set; } = "";
    public string GdbPath { get; set; } = "";
    public string LastProject { get; set; } = "";
    public string NativeSdkDirectory { get; set; } = "";
    public string NativeWorkDirectory { get; set; } = "";
}
