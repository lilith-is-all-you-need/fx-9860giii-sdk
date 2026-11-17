using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace FxStudio.App;

public partial class MainWindow
{
    private async void ImportLegacy_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _gdb != null) return;
        var source = new OpenFolderDialog { Title = T("Choose the original fxlib project", "选择原 fxlib 工程目录") };
        if (source.ShowDialog(this) != true) return;
        var values = Dialogs.Fields(this, T("Migrate fxlib project", "迁移旧 fxlib 工程"),
            (T("New project folder name", "新工程目录名"), Path.GetFileName(source.FolderName) + "-gint"));
        if (values == null) return;
        var name = values[0].Trim();
        if (name.Length == 0 || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name is "." or "..") {
            MessageBox.Show(this, T("Choose a valid project folder name.", "请填写有效的工程目录名。")); return;
        }
        var parent = new OpenFolderDialog { Title = T("Choose the new project's parent folder", "选择新工程的父目录") };
        if (parent.ShowDialog(this) != true || !ConfirmSave()) return;
        var destination = Path.Combine(parent.FolderName, name);
        await RunOperation(async () => {
            await CreateLegacyProjectAsync(source.FolderName, destination, name);
        });
    }

    internal async Task CreateLegacyProjectAsync(string source, string destination, string name)
    {
        var report = await RunProjectToolAsync("legacy_project.py", ["create", "--source", source, "--output", destination, "--name", name]);
        await OpenProject(destination);
        ShowMigrationReport(report);
        var notes = Path.Combine(destination, "migration-report.json");
        if (File.Exists(notes)) OpenDocument(notes);
        SetStatus(T("Project copied and configured. Review the migration report, then build.", "已复制并配置新工程；请查看迁移报告后构建。"));
    }

    private async void ImportResource_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _gdb != null || _project == null || _importedBuild) return;
        var input = new OpenFileDialog {
            Title = T("Choose a resource", "选择资源文件"),
            Filter = "Images|*.png;*.bmp;*.jpg;*.jpeg;*.gif;*.tif;*.tiff|All files|*.*"
        };
        if (input.ShowDialog(this) != true) return;
        var symbol = Regex.Replace(Path.GetFileNameWithoutExtension(input.FileName), "[^a-zA-Z0-9_]", "_");
        if (symbol.Length == 0 || !Regex.IsMatch(symbol[..1], "[a-zA-Z]")) symbol = "asset_" + symbol;
        var panel = new StackPanel { Margin = new Thickness(20) };
        panel.Children.Add(new TextBlock { Text = input.FileName, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 14) });
        var kinds = new[] { "bitmap", "image", "binary" };
        var formats = new ComboBox {
            ItemsSource = new[] { T("fxlib monochrome bitmap", "fxlib 单色位图"), T("gint image (fxconv)", "gint 图片（fxconv）"), T("Binary byte array", "二进制字节数组") },
            SelectedIndex = ImageExtensions.Contains(Path.GetExtension(input.FileName)) ? (Directory.Exists(Path.Combine(_project.SourceDirectory, "compat", "fxlib")) ? 0 : 1) : 2,
            Margin = new Thickness(0, 4, 0, 10)
        };
        panel.Children.Add(new TextBlock { Text = T("Resource format", "资源格式") }); panel.Children.Add(formats);
        panel.Children.Add(new TextBlock { Text = T("C symbol", "C 符号名") });
        var symbolField = new TextBox { Text = symbol, Margin = new Thickness(0, 4, 0, 10) }; panel.Children.Add(symbolField);
        panel.Children.Add(new TextBlock { Text = T("Build target (leave blank for a project with one target)", "构建目标（单目标工程可留空）") });
        var targetField = new TextBox { Margin = new Thickness(0, 4, 0, 10) }; panel.Children.Add(targetField);
        panel.Children.Add(new TextBlock {
            Text = T("The importer adds the resource, declarations and build rules. Bitmap conversion uses a 128 brightness threshold and treats transparency as white. Existing symbols are checked for conflicts. Bitmap fonts can be imported with the command-line tool.", "导入后自动添加资源、声明和构建规则。单色位图以亮度 128 为阈值，透明区域按白色处理；已有符号会检查冲突。位图字体可使用命令行工具导入。"),
            TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 14)
        });
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var cancel = new Button { Content = T("Cancel", "取消"), IsCancel = true };
        var import = new Button { Content = T("Import", "导入"), IsDefault = true };
        buttons.Children.Add(cancel); buttons.Children.Add(import); panel.Children.Add(buttons);
        var dialog = new Window { Owner = this, Title = T("Import resource", "导入资源"), Width = 560, SizeToContent = SizeToContent.Height, ResizeMode = ResizeMode.NoResize, Content = panel, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        import.Click += (_, _) => dialog.DialogResult = true;
        if (dialog.ShowDialog() != true) return;
        var arguments = new List<string> { "import", "--project", _project.SourceDirectory, "--input", input.FileName, "--kind", kinds[formats.SelectedIndex], "--symbol", symbolField.Text.Trim() };
        if (!string.IsNullOrWhiteSpace(targetField.Text)) arguments.AddRange(["--target", targetField.Text.Trim()]);
        await RunOperation(async () => { await ImportProjectResourceAsync(arguments); });
    }

    internal async Task ImportProjectResourceAsync(IEnumerable<string> arguments)
    {
            SaveAll();
            var report = await RunProjectToolAsync("project_assets.py", arguments);
            _artifact = null;
            // SaveAll completed first, so these reloads cannot discard editor changes.
            foreach (var doc in _documents.Values) {
                if (!File.Exists(doc.Path)) continue;
                var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(doc.Path)));
                if (hash == doc.DiskHash) continue;
                doc.Editor.Text = File.ReadAllText(doc.Path, new UTF8Encoding(false, true));
                doc.Dirty = false; doc.DiskHash = hash; doc.Title.Text = Path.GetFileName(doc.Path);
            }
            RefreshTree(); ShowMigrationReport(report);
            if (report.TryGetProperty("header", out var header) && header.GetString() is { } path && File.Exists(path)) OpenDocument(path);
            SetStatus(T("Resource imported. Include project_assets.h to use it.", "资源已导入；包含 project_assets.h 即可使用。"));
    }

    private void ShowMigrationReport(JsonElement report)
    {
        AppendOutput(JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
        InspectorTabs.SelectedIndex = 0;
    }

    internal async Task<JsonElement> RunProjectToolAsync(string scriptName, IEnumerable<string> arguments)
    {
        var script = Path.Combine(App.RootDirectory, "tooling", scriptName);
        if (!File.Exists(script)) throw new FileNotFoundException(T("This package does not include project migration tools. Use a complete updated package.", "当前安装包缺少工程迁移工具，请使用完整更新包。"), script);
        var sdkRoots = new[] { App.LaunchSdkOverride, _project?.NativeSdkDirectory, App.Settings.NativeSdkDirectory, Path.Combine(App.RootDirectory, "sdk", "native"), Path.Combine(App.RootDirectory, "dist-toolchain", "native-sdk") };
        var python = sdkRoots.Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => Path.Combine(x!, "host", "python", "python.exe")).FirstOrDefault(File.Exists)
            ?? throw new FileNotFoundException(T("The native SDK Python runtime is missing. Select the SDK in Settings.", "未找到原生 SDK 的 Python，请在设置中选择 SDK。"));
        _operationCancellation?.Dispose(); _operationCancellation = new CancellationTokenSource();
        var token = _operationCancellation.Token;
        var start = new ProcessStartInfo(python) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var arg in new[] { "-X", "utf8", script }.Concat(arguments)) start.ArgumentList.Add(arg);
        using var process = Process.Start(start) ?? throw new IOException("Unable to start the project tool.");
        // File import commits several related files. Stop/close must wait for
        // completion or the tool's rollback, never kill it mid-transaction.
        using var registration = token.Register(() => Dispatcher.BeginInvoke(() => SetStatus(T("Finishing file changes before stopping…", "正在完成文件写入，随后停止…"))));
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var output = await stdout; var error = await stderr;
        if (process.ExitCode != 0) throw new IOException(string.IsNullOrWhiteSpace(error) ? output : error);
        if (!string.IsNullOrWhiteSpace(error)) AppendOutput(error);
        using var document = JsonDocument.Parse(output);
        return document.RootElement.Clone();
    }
}
