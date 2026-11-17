using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using FxStudio.Core;
using ICSharpCode.AvalonEdit;
using ICSharpCode.AvalonEdit.Highlighting;
using ICSharpCode.AvalonEdit.Search;

namespace FxStudio.App;

public partial class MainWindow : Window
{
    private ProjectConfig? _project;
    private string? _projectFile;
    private BuildArtifact? _artifact;
    private bool _importedBuild;
    private readonly BuildService _builder = new();
    private GdbSession? _gdb;
    private EmulatorSession? _emulator;
    private NativeDebugImage? _debugImage;
    private CancellationTokenSource? _operationCancellation;
    private readonly Dictionary<string, EditorDocument> _documents = new(StringComparer.OrdinalIgnoreCase);
    private readonly ObservableCollection<SourceBreakpoint> _breakpoints = [];
    private readonly ObservableCollection<WatchRow> _watches = [];
    private readonly DispatcherTimer _screenTimer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private bool _busy, _starting, _stopping, _stopRequested, _closing, _allowClose, _refreshing;
    private Task? _currentOperation;
    private Task? _stopTask;
    private bool _refreshPending;
    private string? _executionFile;
    private int? _executionLine;
    private int _refreshVersion;
    private DateTime _screenTimestamp;
    private readonly string? _initialProject;
    private static string T(string en, string zh) => FxStudio.App.Language.Text(en, zh);
    private EditorDocument? ActiveDocument => (EditorTabs.SelectedItem as TabItem)?.Tag as EditorDocument;
    private bool IsStopped => _gdb?.State == DebugState.Stopped;
    private DebugFrame? _selectedFrame;
    private int _selectedFrameLevel;
    private Window? _screenWindow;

    public MainWindow(string? initialProject, bool startImportedBuild = false, bool buildAndDebug = false)
    {
        InitializeComponent();
        _initialProject = initialProject;
        _builder.Log += text => Dispatcher.BeginInvoke(() => AppendOutput(text));
        BreakpointsGrid.ItemsSource = _breakpoints;
        WatchGrid.ItemsSource = _watches;
        ConfigureColumns();
        foreach (var grid in new[] { LocalsGrid, WatchGrid, RegistersGrid, BreakpointsGrid }) grid.SelectionChanged += (_, _) => UpdateButtons();
        AddKeys(FunctionKeys, ["F1", "F2", "F3", "F4", "F5", "F6"]);
        AddKeys(ControlKeys, ["SHIFT", "ALPHA", "LEFT", "UP", "DOWN", "RIGHT", "MENU", "EXIT", "OPTN", "VARS", "DEL", "AC"]);
        AddKeys(NumberKeys, ["7", "8", "9", "MULT", "DIV", "4", "5", "6", "PLUS", "MINUS", "1", "2", "3", "LPAR", "RPAR", "0", "DP", "NEG", "EXP", "EXE"]);
        _screenTimer.Tick += (_, _) => ReadScreen();
        _screenTimer.Start();
        LocalsGrid.MouseDoubleClick += async (_, _) => { if (LocalsGrid.SelectedItem is DebugVariable v) await RunOperation(() => InspectVariable(v.Name)); };
        WatchGrid.MouseDoubleClick += async (_, _) => { if (WatchGrid.SelectedItem is WatchRow v) await RunOperation(() => InspectVariable(v.Expression)); };
        Loaded += async (_, _) => {
            UpdateButtons();
            var path = _initialProject ?? App.Settings.LastProject;
            if (!string.IsNullOrWhiteSpace(path) && (File.Exists(path) || Directory.Exists(path))) await RunOperation(async () => {
                if (path.EndsWith(".fxdebug.json", StringComparison.OrdinalIgnoreCase)) { await LoadCompiledProgram(path); if (startImportedBuild && _artifact != null) await StartDebug(_artifact); }
                else { await OpenProject(path); if (buildAndDebug && _project != null) await StartDebug(await BuildProject(true)); }
            });
        };
    }

    private void ConfigureColumns()
    {
        static void Columns(DataGrid grid, params (string header, string property)[] columns) {
            grid.AutoGenerateColumns = false; grid.Columns.Clear();
            foreach (var (header, property) in columns) grid.Columns.Add(new DataGridTextColumn { Header = header, Binding = new System.Windows.Data.Binding(property), Width = new DataGridLength(1, DataGridLengthUnitType.Star) });
        }
        Columns(LocalsGrid, (T("Name", "名称"), "Name"), (T("Value", "值"), "Value"), (T("Type", "类型"), "Type"));
        Columns(WatchGrid, (T("Expression", "表达式"), "Expression"), (T("Value", "值"), "Value"));
        Columns(StackGrid, (T("Frame", "栈帧"), "Level"), (T("Function", "函数"), "Function"), (T("File", "文件"), "LocalPath"), (T("Line", "行"), "Line"), (T("Address", "地址"), "Address"));
        Columns(BreakpointsGrid, ("ID", "Number"), (T("Location", "位置"), "DisplayLocation"), (T("Condition", "条件"), "Condition"), (T("Status", "状态"), "DisplayStatus"));
        Columns(RegistersGrid, (T("Register", "寄存器"), "Name"), (T("Value", "值"), "Value"));
        Columns(DisassemblyGrid, (T("Address", "地址"), "Address"), (T("Function", "函数"), "Function"), (T("Instruction", "指令"), "Instruction"), (T("Bytes", "字节"), "Opcodes"));
    }

    private void AddKeys(Panel panel, string[] keys)
    {
        foreach (var key in keys) {
            var label = key switch { "LEFT" => "◀", "RIGHT" => "▶", "UP" => "▲", "DOWN" => "▼", "MULT" => "×", "DIV" => "÷", "PLUS" => "+", "MINUS" => "−", "LPAR" => "(", "RPAR" => ")", "DP" => ".", "NEG" => "(−)", _ => key };
            var button = new Button { Content = label, Tag = key, FontSize = key.Length > 3 ? 9 : 12, Padding = new Thickness(2, 5, 2, 5), MinHeight = 28, Margin = new Thickness(2), Focusable = false, ToolTip = key };
            if (key == "EXE") { button.Background = new SolidColorBrush(Color.FromRgb(221,239,233)); button.FontWeight = FontWeights.SemiBold; }
            button.Click += async (_, _) => {
                var emu = _emulator;
                if (emu == null || !emu.IsAlive || _gdb?.State != DebugState.Running) { SetStatus(T("Continue execution before pressing calculator keys.", "继续运行后再按计算器按键。")); return; }
                try { await emu.SendKeyAsync(key, true); await Task.Delay(120); }
                catch (Exception ex) { AppendOutput(ex.Message); }
                finally { try { if (emu.IsAlive) await emu.SendKeyAsync(key, false); } catch (Exception ex) { AppendOutput(ex.Message); } }
            };
            panel.Children.Add(button);
        }
    }

    private void AppendOutput(string text)
    {
        if (OutputText.Text.Length > 250000) OutputText.Text = OutputText.Text[^150000..];
        OutputText.AppendText(text.EndsWith('\n') ? text : text + Environment.NewLine);
        OutputText.ScrollToEnd();
    }
    private void SetStatus(string text) => StatusText.Text = text;
    private void UpdateButtons()
    {
        var running = _gdb?.State == DebugState.Running;
        var available = !_busy && !_refreshing && !_stopping && !_stopRequested && !_closing;
        var inspect = available && IsStopped;
        BuildButton.IsEnabled = _project != null && !_importedBuild && !_busy && _gdb == null;
        ImportLegacyMenu.IsEnabled = available && _gdb == null;
        ImportResourceMenu.IsEnabled = available && _project != null && !_importedBuild && _gdb == null;
        BuildProfile.IsEnabled = !_importedBuild && !_busy && _gdb == null;
        StartButton.IsEnabled = _project != null && available && (_gdb == null || IsStopped);
        PauseButton.IsEnabled = available && running;
        StopButton.IsEnabled = _gdb != null || _emulator != null || _busy;
        NextButton.IsEnabled = StepButton.IsEnabled = FinishButton.IsEnabled = inspect;
        RestartMenu.IsEnabled = _project != null && available;
        RunToMenu.IsEnabled = inspect && ActiveDocument != null;
        BreakpointMenu.IsEnabled = available && !running && ActiveDocument != null;
        EditLocalButton.IsEnabled = inspect && LocalsGrid.SelectedItem != null;
        EditWatchButton.IsEnabled = inspect && WatchGrid.SelectedItem != null;
        EditRegisterButton.IsEnabled = inspect && RegistersGrid.SelectedItem != null;
        ReadMemoryButton.IsEnabled = WriteMemoryButton.IsEnabled = inspect;
        var editBreakpoint = available && (_gdb == null || IsStopped);
        RemoveBreakpointButton.IsEnabled = ToggleEnabledButton.IsEnabled = editBreakpoint && BreakpointsGrid.SelectedItem != null;
        ConditionButton.IsEnabled = editBreakpoint && BreakpointsGrid.SelectedItem is SourceBreakpoint { Expression.Length: 0 };
        WatchpointButton.IsEnabled = editBreakpoint && _project != null;
        EnlargeScreenButton.IsEnabled = SaveScreenButton.IsEnabled = ScreenImage.Source != null;
        foreach (var panel in new[] { FunctionKeys, ControlKeys, NumberKeys }) panel.IsEnabled = running && !_stopping;
        StartButton.ToolTip = IsStopped ? T("Continue the paused program (F5).", "继续已暂停的程序（F5）。") : T("Build Debug and stop at main (F5).", "构建 Debug 并停在 main（F5）。");
        PauseButton.ToolTip = T("Pause the running program to inspect variables and memory.", "暂停运行中的程序，检查变量和内存。");
        StopButton.ToolTip = T("End this debug session (Shift+F5).", "结束当前调试会话（Shift+F5）。");
        foreach (var button in new[] { EditLocalButton, EditWatchButton, EditRegisterButton }) button.ToolTip = T("Pause and select a row to change its value.", "暂停并选中一行后可修改其值。");
        NextButton.ToolTip = T("Pause first. Execute the next source line (F10).", "暂停后执行下一行源码（F10）。");
        StepButton.ToolTip = T("Pause first. Enter the next function call (F11).", "暂停后进入下一次函数调用（F11）。");
        FinishButton.ToolTip = T("Pause first. Run until this function returns (Shift+F11).", "暂停后运行至当前函数返回（Shift+F11）。");
        ToggleEnabledButton.ToolTip = T("Pause and select a breakpoint. Disabled breakpoints stay in the project.", "暂停并选中断点；禁用后仍保留该断点。");
        KeyStatus.Text = running ? T("Click a key to send a short press.", "点击按键发送一次短按。") : T("Continue execution to use calculator keys.", "继续运行后可操作计算器按键。");
        foreach (var grid in new[] { LocalsGrid, WatchGrid, StackGrid, RegistersGrid, DisassemblyGrid }) grid.Opacity = running ? 0.55 : 1;
        foreach (var doc in _documents.Values) doc.Editor.IsReadOnly = _importedBuild || _gdb != null || _busy;
        UpdateDebugPresentation();
    }
    private async Task RunOperation(Func<Task> action)
    {
        if (_busy || _refreshing || _stopping || _stopRequested || _closing) return;
        _busy = true; UpdateButtons();
        try { _currentOperation = action(); await _currentOperation; }
        catch (OperationCanceledException) { SetStatus(T("Cancelled", "已取消")); AppendOutput(T("Operation cancelled.", "操作已取消。")); }
        catch (Exception ex) { SetStatus(T("Operation failed", "操作失败")); AppendOutput(ex.ToString()); InspectorTabs.SelectedIndex = 0; if (!App.IsVerification) MessageBox.Show(this, ex.Message, "Fx Studio", MessageBoxButton.OK, MessageBoxImage.Error); }
        finally { _currentOperation = null; _busy = false; UpdateButtons(); }
    }

    private void ReadScreen()
    {
        var path = _emulator?.FramebufferPath;
        if (path == null || !File.Exists(path)) return;
        try {
            var stamp = File.GetLastWriteTimeUtc(path);
            if (stamp == _screenTimestamp) return;
            var bytes = File.ReadAllBytes(path);
            using var stream = new MemoryStream(bytes, false);
            var bitmap = BitmapFrame.Create(stream, BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
            bitmap.Freeze();
            ScreenImage.Source = bitmap; ScreenPlaceholder.Visibility = Visibility.Collapsed; _screenTimestamp = stamp;
            EnlargeScreenButton.IsEnabled = SaveScreenButton.IsEnabled = true;
        } catch (IOException) { /* The next timer tick retries an atomic replacement. */ }
          catch (NotSupportedException) { }
          catch (FileFormatException) { }
    }
    private void UpdateDecorations()
    {
        foreach (var doc in _documents.Values) { doc.Margin.InvalidateVisual(); doc.Editor.TextArea.TextView.InvalidateLayer(ICSharpCode.AvalonEdit.Rendering.KnownLayer.Background); }
    }
    private void UpdateCaret() { var d = ActiveDocument; CaretText.Text = d == null ? "" : $"{Path.GetFileName(d.Path)}   Ln {d.Editor.TextArea.Caret.Line}, Col {d.Editor.TextArea.Caret.Column}   UTF-8"; }
    private void EditorTabs_SelectionChanged(object sender, SelectionChangedEventArgs e) { UpdateCaret(); if (IsLoaded) UpdateButtons(); }
    private void Find_Click(object sender, RoutedEventArgs e) { if (ActiveDocument is { } doc) { doc.Search.Open(); doc.Search.Reactivate(); } }
    private void English_Click(object sender, RoutedEventArgs e) => SwitchLanguage("en");
    private void Chinese_Click(object sender, RoutedEventArgs e) => SwitchLanguage("zh-CN");
    private void SwitchLanguage(string language) { FxStudio.App.Language.Set(language); ConfigureColumns(); BreakpointsGrid.Items.Refresh(); UpdateButtons(); App.Settings.Language = language; App.SaveSettings(); }
    private void Exit_Click(object sender, RoutedEventArgs e) => Close();
    private void Guide_Click(object sender, RoutedEventArgs e)
    {
        var path = Path.Combine(App.RootDirectory, "docs", FxStudio.App.Language.Chinese ? "USER-GUIDE.zh-CN.html" : "USER-GUIDE.en.html");
        if (File.Exists(path)) Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        else MessageBox.Show(this, T("Open a CMake project or the included example. Build with Ctrl+Shift+B, start with F5, toggle breakpoints with F9, step with F10/F11. Stop with Shift+F5. Use Debug for debugging and Release for deployment.", "打开 CMake 工程或附带示例。Ctrl+Shift+B 构建，F5 启动，F9 切换断点，F10/F11 单步，Shift+F5 停止。调试使用 Debug，部署使用 Release。"), "Fx Studio");
    }
    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _gdb != null) return;
        var values = Dialogs.Fields(this, T("Settings", "设置"), (T("WSL distribution", "WSL 发行版"), App.Settings.Distro), (T("Emulator executable (blank: bundled)", "模拟器程序（留空使用随包版本）"), App.Settings.EmulatorPath), (T("Native GDB executable (blank: bundled)", "原生 GDB 程序（留空使用随包版本）"), App.Settings.GdbPath), (T("Native SDK folder (blank: bundled)", "原生 SDK 目录（留空使用随包版本）"), App.Settings.NativeSdkDirectory), (T("Native build cache (blank: temporary folder)", "原生构建缓存（留空使用临时目录）"), App.Settings.NativeWorkDirectory));
        if (values == null) return;
        if (string.IsNullOrWhiteSpace(values[0])) { MessageBox.Show(this, T("A WSL distribution name is required.", "必须填写 WSL 发行版名称。")); return; }
        App.Settings.Distro = values[0].Trim(); App.Settings.EmulatorPath = values[1].Trim(); App.Settings.GdbPath = values[2].Trim(); App.SaveSettings();
        App.Settings.NativeSdkDirectory = values[3].Trim(); App.Settings.NativeWorkDirectory = values[4].Trim(); App.SaveSettings();
        if (_project != null) _project = _project with { Distro = App.Settings.Distro };
    }
    private void Window_KeyDown(object sender, KeyEventArgs e)
    {
        var ctrl = Keyboard.Modifiers.HasFlag(ModifierKeys.Control);
        var shift = Keyboard.Modifiers.HasFlag(ModifierKeys.Shift);
        var alt = Keyboard.Modifiers.HasFlag(ModifierKeys.Alt);
        var key = e.Key == Key.System ? e.SystemKey : e.Key;
        if (ctrl && alt && key is Key.F10 or Key.F11) {
            if (StepButton.IsEnabled) { if (key == Key.F10) NextInstruction_Click(sender, e); else StepInstruction_Click(sender, e); }
            e.Handled = true; return;
        }
        // WPF can report F10 as Key.System even without Alt; normalize it here too.
        if (alt) return;
        if (ctrl && e.Key == Key.S) { SaveAll_Click(sender, e); e.Handled = true; }
        else if (ctrl && e.Key == Key.O) { Open_Click(sender, e); e.Handled = true; }
        else if (ctrl && e.Key == Key.N) { New_Click(sender, e); e.Handled = true; }
        else if (ctrl && e.Key == Key.F) { Find_Click(sender, e); e.Handled = true; }
        else if (ctrl && shift && e.Key == Key.B) { Build_Click(sender, e); e.Handled = true; }
        else if (e.Key == Key.F5) { if (shift) Stop_Click(sender, e); else Start_Click(sender, e); e.Handled = true; }
        else if (e.Key == Key.F9) { Breakpoint_Click(sender, e); e.Handled = true; }
        else if (key == Key.F10) { if (ctrl) RunTo_Click(sender, e); else Next_Click(sender, e); e.Handled = true; }
        else if (e.Key == Key.F11) { if (shift) Finish_Click(sender, e); else Step_Click(sender, e); e.Handled = true; }
    }
    private async void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_allowClose) return;
        e.Cancel = true;
        if (_closing) return;
        if (!ConfirmSave()) return;
        _closing = true;
        try { _operationCancellation?.Cancel(); if (_currentOperation is { } active) { try { await active; } catch { } } await StopDebug(); SaveSessionState(); App.SaveSettings(); _screenTimer.Stop(); _allowClose = true; _ = Dispatcher.BeginInvoke(Close); }
        catch (Exception ex) { _closing = false; MessageBox.Show(this, ex.Message, "Fx Studio"); }
    }
}

internal sealed class EditorDocument(string path, TextEditor editor, TabItem tab, TextBlock title, BreakpointMargin margin, SearchPanel search)
{
    public string Path { get; } = path;
    public TextEditor Editor { get; } = editor;
    public TabItem Tab { get; } = tab;
    public TextBlock Title { get; } = title;
    public BreakpointMargin Margin { get; } = margin;
    public SearchPanel Search { get; } = search;
    public bool Dirty { get; set; }
    public string DiskHash { get; set; } = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path)));
    public Dictionary<SourceBreakpoint, ICSharpCode.AvalonEdit.Document.TextAnchor> BreakpointAnchors { get; } = [];
}
internal sealed class SourceBreakpoint
{
    public string File { get; set; } = "";
    public int Line { get; set; }
    public string Condition { get; set; } = "";
    public string Number { get; set; } = "";
    public string Status { get; set; } = "Pending build";
    public bool Enabled { get; set; } = true;
    public string DisplayStatus => !Enabled ? Language.Text("Disabled", "已禁用") : Status switch {
        "Pending build" => Language.Text("Pending build", "待构建"),
        "Pending symbol" => Language.Text("Pending symbol", "待解析符号"),
        "Verified" => Language.Text("Enabled", "已启用"), _ => Status
    };
    public string Expression { get; set; } = "";
    public string Access { get; set; } = "write";
    public string DisplayLocation => Expression.Length > 0 ? $"{Access}: {Expression}" : $"{Path.GetFileName(File)}:{Line}";
}
internal sealed class WatchRow(string expression, string value = "")
{
    public string Expression { get; set; } = expression;
    public string Value { get; set; } = value;
}
