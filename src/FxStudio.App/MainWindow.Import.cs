using System.IO;
using System.Text.Json;
using System.Windows;
using FxStudio.Core;
using Microsoft.Win32;

namespace FxStudio.App;

public partial class MainWindow
{
    private async void ImportBuild_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var dialog = new OpenFileDialog { Title = T("Load compiled SuperH program", "加载已编译的 SuperH 程序"), Filter = "Fx Studio debug bundle|*.fxdebug.json" };
        if (dialog.ShowDialog(this) == true) await RunOperation(() => LoadCompiledProgram(dialog.FileName));
    }

    private async Task LoadCompiledProgram(string path)
    {
        if (!ConfirmSave()) return;
        path = Path.GetFullPath(path);
        var root = Path.GetDirectoryName(path)!;
        var descriptor = JsonSerializer.Deserialize<CompiledProgram>(await File.ReadAllTextAsync(path), new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidDataException("Empty debug descriptor.");
        if (descriptor.SchemaVersion != 1) throw new InvalidDataException("Unsupported debug descriptor version.");
        string Resolve(string value) => string.IsNullOrWhiteSpace(value) ? throw new InvalidDataException("Empty file path in debug descriptor.") : Path.GetFullPath(value, root);
        var source = Resolve(descriptor.SourceDirectory);
        if (!Directory.Exists(source)) throw new DirectoryNotFoundException(source);
        var artifact = new BuildArtifact {
            ElfPath = Resolve(descriptor.Elf), G1APath = Resolve(descriptor.G1a), ManifestPath = path,
            Configuration = BuildConfiguration.Debug, LinuxElfPath = "", LinuxG1APath = "", LinuxSourceDirectory = "", LinuxBuildDirectory = "",
            ElfSha256 = descriptor.ElfSha256, G1ASha256 = descriptor.G1aSha256,
            SourceMappings = descriptor.SourceMappings.Select(m => new SourceMapping(m.From, Resolve(m.To))).ToArray()
        };
        var verified = await artifact.VerifyAsync();
        await StopDebug(); SaveSessionState();
        _project = new ProjectConfig { Name = descriptor.Name, SourceDirectory = source, BuildDirectory = Path.GetDirectoryName(artifact.ElfPath)!, Distro = App.Settings.Distro };
        _projectFile = null; _importedBuild = true; _artifact = artifact;
        _documents.Clear(); EditorTabs.Items.Clear(); EditorTabs.Visibility = Visibility.Collapsed; WelcomeText.Visibility = Visibility.Visible;
        _breakpoints.Clear(); _watches.Clear(); ScreenImage.Source = null; ScreenPlaceholder.Visibility = Visibility.Visible;
        RefreshTree(); ProjectTitle.Text = descriptor.Name; Title = descriptor.Name + " — Fx Studio";
        var main = new[] { "src/main.cpp", "src/main.c", "main.cpp", "main.c" }.Select(p => Path.Combine(source, p)).FirstOrDefault(File.Exists);
        if (main != null) OpenDocument(main);
        AppendOutput($"Loaded existing build: {artifact.G1APath}\nELF/G1A verified: {verified.ComparedBytes:N0} bytes.\nSource files are read-only; F5 runs this verified build.");
        SetStatus(T("Existing build loaded · F5 to debug · source is read-only", "已有产物已加载 · F5 调试 · 源码只读"));
    }
}

internal sealed class CompiledProgram
{
    public int SchemaVersion { get; set; } = 1;
    public string Name { get; set; } = "Imported SuperH program";
    public string Elf { get; set; } = "";
    public string G1a { get; set; } = "";
    public string SourceDirectory { get; set; } = ".";
    public string? ElfSha256 { get; set; }
    public string? G1aSha256 { get; set; }
    public List<SourceMapping> SourceMappings { get; set; } = [];
}
