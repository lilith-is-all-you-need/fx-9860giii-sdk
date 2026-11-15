using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using FxStudio.Core;
using ICSharpCode.AvalonEdit;
using ICSharpCode.AvalonEdit.Highlighting;
using ICSharpCode.AvalonEdit.Search;
using Microsoft.Win32;

namespace FxStudio.App;

public partial class MainWindow
{
    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var dialog = new OpenFileDialog { Title = T("Open CMake or Fx Studio project", "打开 CMake 或 Fx Studio 工程"), Filter = "Projects|CMakeLists.txt;*.fxide.json|All files|*.*" };
        if (dialog.ShowDialog(this) == true) await RunOperation(() => OpenProject(dialog.FileName));
    }
    private async void New_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var values = Dialogs.Fields(this, T("New project", "新建工程"), (T("Project name", "工程名称"), "MyAddin"), (T("Language: C or C++", "语言：C 或 C++"), "C++"));
        if (values == null) return;
        var name = values[0].Trim();
        if (name.Length == 0 || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name is "." or "..") { MessageBox.Show(this, T("Choose a valid project folder name.", "请填写有效的工程目录名。")); return; }
        if (values[1] is not ("C" or "C++" or "c" or "cpp")) { MessageBox.Show(this, "C / C++"); return; }
        var folder = new OpenFolderDialog { Title = T("Choose parent folder", "选择父目录") };
        if (folder.ShowDialog(this) != true) return;
        var destination = Path.Combine(folder.FolderName, name);
        await RunOperation(async () => {
            if (Directory.Exists(destination) && Directory.EnumerateFileSystemEntries(destination).Any()) throw new IOException(T("The destination is not empty.", "目标目录不是空目录。"));
            CopyExample(values[1].Equals("C", StringComparison.OrdinalIgnoreCase) ? "counter-c" : "counter-cpp", destination);
            await OpenProject(destination);
        });
    }
    private async void Demo_Click(object sender, RoutedEventArgs e)
    {
        await RunOperation(async () => {
            var destination = Path.Combine(App.DataDirectory, "Projects", "Counter-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
            CopyExample("counter-cpp", destination);
            await OpenProject(destination);
        });
    }
    private static void CopyExample(string name, string destination)
    {
        var source = Path.Combine(App.RootDirectory, "examples", name);
        if (!Directory.Exists(source)) throw new DirectoryNotFoundException("Bundled example not found: " + source);
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories)) {
            var relative = Path.GetRelativePath(source, file);
            if (relative.Split(Path.DirectorySeparatorChar).Any(x => x.StartsWith("build") || x == ".fxstudio")) continue;
            var target = Path.Combine(destination, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(file, target, false);
        }
    }
    private async Task OpenProject(string path)
    {
        if (!ConfirmSave()) return;
        path = Path.GetFullPath(path);
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path)!;
        string nextProjectFile;
        ProjectConfig nextProject;
        if (path.EndsWith(".fxide.json", StringComparison.OrdinalIgnoreCase)) {
            nextProjectFile = path; nextProject = await ProjectConfig.LoadAsync(path);
        } else {
            if (!File.Exists(Path.Combine(folder, "CMakeLists.txt"))) throw new FileNotFoundException("CMakeLists.txt not found.");
            nextProjectFile = Path.Combine(folder, "project.fxide.json");
            if (File.Exists(nextProjectFile)) nextProject = await ProjectConfig.LoadAsync(nextProjectFile);
            else nextProject = new ProjectConfig { Name = Path.GetFileName(folder), SourceDirectory = folder, BuildDirectory = Path.Combine(folder, ".fxstudio", "build"), Distro = App.Settings.Distro };
        }
        if (!Directory.Exists(nextProject.SourceDirectory) || !File.Exists(Path.Combine(nextProject.SourceDirectory, "CMakeLists.txt"))) throw new DirectoryNotFoundException("Project source or CMakeLists.txt not found.");
        await StopDebug(); SaveSessionState();
        _project = nextProject; _projectFile = nextProjectFile; _importedBuild = false;
        _artifact = null; _documents.Clear(); EditorTabs.Items.Clear(); EditorTabs.Visibility = Visibility.Collapsed; WelcomeText.Visibility = Visibility.Visible;
        _breakpoints.Clear(); _watches.Clear(); ScreenImage.Source = null; ScreenPlaceholder.Visibility = Visibility.Visible;
        LoadSessionState(); RefreshTree();
        ProjectTitle.Text = _project.Name; Title = _project.Name + " — Fx Studio";
        App.Settings.LastProject = _projectFile; App.SaveSettings();
        await _project.SaveAsync(_projectFile);
        var main = new[] { "src/main.cpp", "src/main.c", "main.cpp", "main.c" }.Select(p => Path.Combine(_project.SourceDirectory, p)).FirstOrDefault(File.Exists);
        OpenDocument(main ?? Path.Combine(_project.SourceDirectory, "CMakeLists.txt"));
        SetStatus(T("Project opened", "工程已打开") + " · " + _project.SourceDirectory);
    }
    private void RefreshTree()
    {
        ProjectTree.Items.Clear();
        if (_project == null) return;
        var root = DirectoryNode(_project.SourceDirectory); root.Header = _project.Name;
        ProjectTree.Items.Add(root); root.IsExpanded = true;
    }
    private TreeViewItem DirectoryNode(string path)
    {
        var item = new TreeViewItem { Header = Path.GetFileName(path), Tag = path, FontWeight = FontWeights.SemiBold };
        item.Items.Add(new TreeViewItem());
        item.Expanded += (_, e) => {
            if (!ReferenceEquals(e.OriginalSource, item) || item.Items.Count != 1 || (item.Items[0] as TreeViewItem)?.Tag != null) return;
            item.Items.Clear();
            try {
                foreach (var child in Directory.EnumerateDirectories(path).OrderBy(p => p, StringComparer.OrdinalIgnoreCase)) {
                    var name = Path.GetFileName(child);
                    if (name is ".git" or ".fxstudio" or ".vs" or "bin" or "obj" || name.StartsWith("build", StringComparison.OrdinalIgnoreCase)) continue;
                    if (File.GetAttributes(child).HasFlag(FileAttributes.ReparsePoint)) continue;
                    item.Items.Add(DirectoryNode(child));
                }
                foreach (var file in Directory.EnumerateFiles(path).OrderBy(p => p, StringComparer.OrdinalIgnoreCase)) item.Items.Add(new TreeViewItem { Header = Path.GetFileName(file), Tag = file, FontWeight = FontWeights.Normal });
            } catch (IOException ex) { AppendOutput(ex.Message); } catch (UnauthorizedAccessException ex) { AppendOutput(ex.Message); }
        };
        var context = new ContextMenu();
        var newFile = new MenuItem { Header = T("New source file…", "新建源文件…") };
        newFile.Click += (_, _) => {
            if (_busy || _importedBuild || _gdb != null) return;
            var values = Dialogs.Fields(this, T("New source file", "新建源文件"), (T("File name", "文件名"), "module.c"));
            if (values == null) return;
            var fileName = values[0].Trim();
            if (fileName.Length == 0 || fileName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || fileName is "." or "..") return;
            var target = Path.Combine(path, fileName);
            try { using (var stream = new FileStream(target, FileMode.CreateNew)) { } RefreshTree(); OpenDocument(target); SetStatus(T("Add the new file to CMakeLists.txt before building.", "构建前请把新文件加入 CMakeLists.txt。")); }
            catch (IOException ex) { MessageBox.Show(this, ex.Message, "Fx Studio"); }
        };
        context.Items.Add(newFile); item.ContextMenu = context;
        return item;
    }
    private void ProjectTree_DoubleClick(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (ProjectTree.SelectedItem is TreeViewItem { Tag: string path } && File.Exists(path)) {
            try { OpenProjectFile(path); } catch (Exception ex) { MessageBox.Show(this, ex.Message, "Fx Studio"); }
        }
    }
    private EditorDocument OpenDocument(string path, int? line = null)
    {
        path = Path.GetFullPath(path);
        if (_documents.TryGetValue(path, out var existing)) { EditorTabs.SelectedItem = existing.Tab; if (line.HasValue) Navigate(existing, line.Value); return existing; }
        if (!IsTextDocument(path)) throw new IOException(T("This file type is not editable text. Use its resource preview in the project tree.", "此文件类型不作为文本编辑，请从工程树查看资源预览。"));
        if (new FileInfo(path).Length > 4 * 1024 * 1024) throw new IOException(T("The editor accepts text files up to 4 MiB.", "编辑器接受最大 4 MiB 的文本文件。"));
        var text = File.ReadAllText(path, new UTF8Encoding(false, true));
        if (text.Any(c => c < ' ' && c is not ('\t' or '\r' or '\n' or '\f'))) throw new IOException(T("This is a binary file; it cannot be edited as text.", "这是二进制文件，不能作为文本编辑。"));
        var editor = new TextEditor { FontFamily = new FontFamily("Cascadia Mono,Consolas"), FontSize = 14, ShowLineNumbers = true, Background = Brushes.White, Foreground = new SolidColorBrush(Color.FromRgb(28, 46, 59)), HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2, 10, 4, 5) };
        editor.Options.ConvertTabsToSpaces = true; editor.Options.IndentationSize = 4;
        editor.SyntaxHighlighting = HighlightingManager.Instance.GetDefinitionByExtension(Path.GetExtension(path)) ?? (Path.GetExtension(path) is ".cpp" or ".c" or ".h" or ".hpp" ? HighlightingManager.Instance.GetDefinition("C++") : null);
        editor.Text = text;
        var title = new TextBlock { Text = Path.GetFileName(path), VerticalAlignment = VerticalAlignment.Center };
        var header = new StackPanel { Orientation = Orientation.Horizontal }; header.Children.Add(title);
        var close = new Button { Content = "×", MinHeight = 18, FontSize = 12, Padding = new Thickness(5, 0, 5, 0), Margin = new Thickness(8, 0, 0, 0), BorderThickness = new Thickness(0), Background = Brushes.Transparent };
        header.Children.Add(close);
        var tab = new TabItem { Header = header, Content = editor, ToolTip = path };
        var captured = path;
        var margin = new BreakpointMargin(n => _breakpoints.FirstOrDefault(b => b.File.Equals(captured, StringComparison.OrdinalIgnoreCase) && b.Line == n && b.Expression.Length == 0)?.Enabled, n => _ = RunOperation(() => ToggleBreakpoint(captured, n)), () => _executionFile != null && _executionFile.Equals(captured, StringComparison.OrdinalIgnoreCase) ? _executionLine : null);
        editor.TextArea.LeftMargins.Insert(0, margin);
        editor.TextArea.TextView.BackgroundRenderers.Add(new ExecutionRenderer(() => _executionFile != null && _executionFile.Equals(captured, StringComparison.OrdinalIgnoreCase) ? _executionLine : null));
        var search = SearchPanel.Install(editor);
        var doc = new EditorDocument(path, editor, tab, title, margin, search); tab.Tag = doc;
        editor.TextChanged += (_, _) => { doc.Dirty = true; doc.Title.Text = Path.GetFileName(path) + " •"; _artifact = null; foreach (var (bp, anchor) in doc.BreakpointAnchors) if (!anchor.IsDeleted) bp.Line = anchor.Line; BreakpointsGrid.Items.Refresh(); UpdateDecorations(); };
        editor.TextArea.Caret.PositionChanged += (_, _) => UpdateCaret();
        close.Click += (_, _) => { if (!ConfirmSave(doc)) return; _documents.Remove(doc.Path); EditorTabs.Items.Remove(tab); if (EditorTabs.Items.Count == 0) EditorTabs.Visibility = Visibility.Collapsed; };
        _documents[path] = doc; EditorTabs.Items.Add(tab); EditorTabs.SelectedItem = tab; EditorTabs.Visibility = Visibility.Visible; WelcomeText.Visibility = Visibility.Collapsed;
        editor.IsReadOnly = _importedBuild || _gdb != null || _busy;
        foreach (var breakpoint in _breakpoints.Where(b => b.File.Equals(path, StringComparison.OrdinalIgnoreCase) && b.Expression.Length == 0)) TrackBreakpoint(doc, breakpoint);
        if (line.HasValue) Navigate(doc, line.Value);
        return doc;
    }
    private static void Navigate(EditorDocument doc, int line)
    {
        line = Math.Clamp(line, 1, doc.Editor.Document.LineCount);
        doc.Editor.TextArea.Caret.Line = line; doc.Editor.TextArea.Caret.Column = 1; doc.Editor.ScrollToLine(line); doc.Editor.Focus();
    }
    private void SaveDocument(EditorDocument doc)
    {
        if (!doc.Dirty) return;
        var diskHash = File.Exists(doc.Path) ? Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(doc.Path))) : "missing";
        if (diskHash != doc.DiskHash) {
            var choice = MessageBox.Show(this, T("This file changed outside Fx Studio. Yes: overwrite it with the editor contents. No: reload the disk version. Cancel: leave both unchanged.", "此文件已被外部修改。是：用编辑器内容覆盖；否：重新载入磁盘版本；取消：保持两者不变。") + "\n\n" + doc.Path, T("File conflict", "文件冲突"), MessageBoxButton.YesNoCancel, MessageBoxImage.Warning);
            if (choice == MessageBoxResult.Cancel) throw new OperationCanceledException();
            if (choice == MessageBoxResult.No) { doc.Editor.Text = File.ReadAllText(doc.Path, new UTF8Encoding(false, true)); doc.Dirty = false; doc.DiskHash = diskHash; doc.Title.Text = Path.GetFileName(doc.Path); return; }
        }
        var temporary = doc.Path + ".fxstudio-" + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temporary, doc.Editor.Text, new UTF8Encoding(false)); File.Move(temporary, doc.Path, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
        doc.Dirty = false; doc.Title.Text = Path.GetFileName(doc.Path); doc.DiskHash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(doc.Path)));
    }
    private static void TrackBreakpoint(EditorDocument doc, SourceBreakpoint breakpoint)
    {
        if (breakpoint.Line < 1 || breakpoint.Line > doc.Editor.Document.LineCount) return;
        var anchor = doc.Editor.Document.CreateAnchor(doc.Editor.Document.GetLineByNumber(breakpoint.Line).Offset);
        anchor.MovementType = ICSharpCode.AvalonEdit.Document.AnchorMovementType.AfterInsertion; anchor.SurviveDeletion = true;
        doc.BreakpointAnchors[breakpoint] = anchor;
    }
    private void SaveAll() { foreach (var doc in _documents.Values) SaveDocument(doc); SaveSessionState(); }
    private bool ConfirmSave(EditorDocument? document = null)
    {
        var dirty = document != null ? (document.Dirty ? new[] { document } : []) : _documents.Values.Where(d => d.Dirty).ToArray();
        if (dirty.Length == 0) return true;
        var result = MessageBox.Show(this, T("Save changes before continuing?", "继续前保存修改吗？"), "Fx Studio", MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
        if (result == MessageBoxResult.Cancel) return false;
        if (result == MessageBoxResult.Yes) { try { foreach (var doc in dirty) SaveDocument(doc); } catch (Exception ex) { MessageBox.Show(this, ex.Message); return false; } }
        return true;
    }
    private async void Save_Click(object sender, RoutedEventArgs e) => await RunOperation(() => { if (ActiveDocument is { } d) SaveDocument(d); return Task.CompletedTask; });
    private async void SaveAll_Click(object sender, RoutedEventArgs e) => await RunOperation(() => { SaveAll(); return Task.CompletedTask; });
    private async void Build_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { await BuildProject(); });
    private async Task<BuildArtifact> BuildProject(bool forceDebug = false)
    {
        if (_project == null) throw new InvalidOperationException(T("Open a project first.", "请先打开工程。"));
        if (_importedBuild) throw new InvalidOperationException(T("This is an imported build. Open its CMake project to rebuild it.", "当前加载的是已有产物。需要重新构建时请打开其 CMake 工程。"));
        if (_gdb != null) throw new InvalidOperationException(T("Stop debugging before building.", "构建前请先停止调试。"));
        SaveAll(); await _project.SaveAsync(_projectFile!); _artifact = null;
        _operationCancellation?.Dispose(); _operationCancellation = new CancellationTokenSource();
        var configuration = forceDebug || BuildProfile.SelectedIndex == 0 ? BuildConfiguration.Debug : BuildConfiguration.Release;
        SetStatus(T("Building", "正在构建") + " · " + configuration); InspectorTabs.SelectedIndex = 0;
        AppendOutput($"\n--- {_project.Name} / {configuration} ---");
        var nativeSdk = App.LaunchSdkOverride ?? (!string.IsNullOrWhiteSpace(_project.NativeSdkDirectory) ? _project.NativeSdkDirectory : App.Settings.NativeSdkDirectory);
        if (string.IsNullOrWhiteSpace(nativeSdk)) nativeSdk = new[] {
            Path.Combine(App.RootDirectory, "sdk", "native"),
            Path.Combine(App.RootDirectory, "dist-toolchain", "native-sdk")
        }.FirstOrDefault(p => File.Exists(Path.Combine(p, "service", "build-native.py"))) ?? "";
        var nativeWork = !string.IsNullOrWhiteSpace(_project.NativeWorkDirectory) ? _project.NativeWorkDirectory : App.Settings.NativeWorkDirectory;
        var artifact = await _builder.BuildAsync(_project with { NativeSdkDirectory = nativeSdk, NativeWorkDirectory = nativeWork }, configuration, _operationCancellation.Token);
        _artifact = artifact;
        AppendOutput($"ELF: {artifact.ElfPath}\nG1A: {artifact.G1APath}\n{artifact.G1ASize:N0} bytes");
        SetStatus(T("Build succeeded", "构建成功") + $" · {artifact.G1ASize:N0} bytes · {configuration}");
        return artifact;
    }
    private void CancelBuild_Click(object sender, RoutedEventArgs e) => _operationCancellation?.Cancel();
    private void Reveal_Click(object sender, RoutedEventArgs e)
    {
        var path = _artifact != null ? Path.GetDirectoryName(_artifact.G1APath) : _project?.BuildDirectory;
        if (path != null && Directory.Exists(path)) Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }
    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var artifact = _debugImage?.Artifact ?? _artifact;
        if (artifact == null || !File.Exists(artifact.G1APath)) { MessageBox.Show(this, T("Build the project first.", "请先构建工程。")); return; }
        var save = new SaveFileDialog { Filter = "Calculator add-in|*.g1a", FileName = Path.GetFileName(artifact.G1APath), OverwritePrompt = true };
        if (save.ShowDialog(this) != true) return;
        await RunOperation(async () => {
            var verified = await artifact.VerifyAsync();
            var bytes = await File.ReadAllBytesAsync(artifact.G1APath);
            ArtifactPairVerifier.CheckExpectedSha256(Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)), verified.G1ASha256, "Exported G1A");
            var temporary = save.FileName + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try { await File.WriteAllBytesAsync(temporary, bytes); File.Move(temporary, save.FileName, true); }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            SetStatus(T("Verified G1A exported; test on your calculator.", "已校验的 G1A 已导出；请在计算器上验证。"));
        });
    }
    private void SaveSessionState()
    {
        if (_project == null || _importedBuild) return;
        var path = Path.Combine(_project.SourceDirectory, ".fxstudio", "session.json");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var data = new SessionState { Breakpoints = _breakpoints.Select(b => new SourceBreakpoint { File = Path.GetRelativePath(_project.SourceDirectory, b.File.Length > 0 ? b.File : _project.SourceDirectory), Line = b.Line, Condition = b.Condition, Expression = b.Expression, Access = b.Access, Enabled = b.Enabled }).ToList(), Watches = _watches.Select(w => w.Expression).ToList() };
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(data, new JsonSerializerOptions { WriteIndented = true })); File.Move(temporary, path, true);
    }
    private void LoadSessionState()
    {
        if (_project == null) return;
        try {
            var data = JsonSerializer.Deserialize<SessionState>(File.ReadAllText(Path.Combine(_project.SourceDirectory, ".fxstudio", "session.json")));
            if (data == null) return;
            foreach (var b in data.Breakpoints) { b.File = Path.GetFullPath(b.File, _project.SourceDirectory); b.Number = ""; b.Status = "Pending build"; _breakpoints.Add(b); }
            foreach (var expression in data.Watches) _watches.Add(new WatchRow(expression));
        } catch (IOException) { } catch (JsonException) { }
    }
}
internal sealed class SessionState
{
    public List<SourceBreakpoint> Breakpoints { get; set; } = [];
    public List<string> Watches { get; set; } = [];
}
