using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using FxStudio.Core;

namespace FxStudio.App;

public partial class MainWindow
{
    private async void Start_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        if (IsStopped) { await _gdb!.ContinueAsync(); return; }
        if (_gdb != null) throw new InvalidOperationException(T("Stop the current session before restarting.", "重新启动前请停止当前会话。"));
        BuildProfile.SelectedIndex = 0;
        var artifact = _importedBuild ? _artifact! : await BuildProject(true);
        await StartDebug(artifact);
    });
    private async Task StartDebug(BuildArtifact artifact)
    {
        if (_project == null) return;
        _operationCancellation?.Dispose(); _operationCancellation = new CancellationTokenSource();
        await artifact.VerifyAsync(_operationCancellation.Token);
        var emulatorPath = App.LaunchEmulatorOverride ?? App.Settings.EmulatorPath;
        if (string.IsNullOrWhiteSpace(emulatorPath)) emulatorPath = new[] {
            Path.Combine(App.RootDirectory, "runtime", "emulator", "FxEmulator.exe"),
            Path.Combine(App.RootDirectory, "probes", "emulator", "build", "FxEmulator.exe")
        }.FirstOrDefault(File.Exists) ?? throw new FileNotFoundException(T("The bundled emulator is missing. Check Settings.", "未找到随包模拟器，请检查设置。"));
        var nativeGdb = FindNativeGdb();
        if (string.IsNullOrEmpty(artifact.LinuxElfPath) && nativeGdb == null) throw new FileNotFoundException(T("This build requires a native GDB. Select it in Settings.", "此产物需要原生 GDB，请在设置中选择。"));
        var sessionFolder = Path.Combine(App.DataDirectory, "Sessions", Guid.NewGuid().ToString("N"));
        if (nativeGdb != null) {
            var nativeWork = !string.IsNullOrWhiteSpace(_project.NativeWorkDirectory) ? _project.NativeWorkDirectory : App.Settings.NativeWorkDirectory;
            _debugImage = await NativeDebugImage.CreateAsync(artifact, nativeWork, _operationCancellation.Token);
            artifact = _debugImage.Artifact; sessionFolder = _debugImage.DirectoryPath;
        } else Directory.CreateDirectory(sessionFolder);
        ScreenImage.Source = null; ScreenPlaceholder.Visibility = Visibility.Visible; _screenTimestamp = default;
        _emulator = new EmulatorSession();
        var emu = _emulator;
        emu.Output += text => Dispatcher.BeginInvoke(() => AppendOutput("[emu] " + text));
        emu.Exited += code => Dispatcher.BeginInvoke(async () => {
            if (_stopping || _emulator != emu) return;
            AppendOutput($"Emulator exited ({code}).");
            await StopDebug(); SetStatus(T("Emulator exited", "模拟器已退出") + $" ({code})");
        });
        _starting = true;
        try {
            await emu.StartAsync(emulatorPath, artifact.G1APath, Path.Combine(sessionFolder, "screen.bmp"), _operationCancellation?.Token ?? default);
            var gdb = new GdbSession(); _gdb = gdb;
            gdb.Output += text => Dispatcher.BeginInvoke(() => AppendOutput("[gdb] " + text));
            gdb.StateChanged += state => Dispatcher.BeginInvoke(async () => {
                if (_gdb != gdb) return;
                if (state == DebugState.Running) { _refreshVersion++; _executionFile = null; _executionLine = null; _selectedFrame = null; _selectedFrameLevel = 0; UpdateDecorations(); SetStatus(T("Running", "正在运行")); }
                else if (state is DebugState.Faulted or DebugState.Exited) {
                    _refreshVersion++;
                    if (!_starting) await StopDebug();
                    SetStatus(T("Debug session ended", "调试会话已结束") + " · " + state);
                }
                UpdateButtons();
            });
            gdb.Stopped += record => Dispatcher.BeginInvoke(async () => {
                if (_gdb != gdb || _starting || _stopping) return;
                var reason = record.GetString("reason") ?? "stopped";
                AppendOutput("[stop] " + DescribeStop(record) + " (" + reason + ")");
                if (reason.StartsWith("exited", StringComparison.Ordinal)) { await StopDebug(); SetStatus(T("Program exited", "程序已退出")); return; }
                await RefreshDebug();
            });
            var options = nativeGdb == null
                ? artifact.CreateWslGdbOptions(_project, emu.GdbPort)
                : artifact.CreateNativeGdbOptions(nativeGdb, emu.GdbPort);
            await gdb.StartAsync(options, _operationCancellation?.Token ?? default);
            await gdb.InsertBreakpointAsync("main", temporary: true);
            foreach (var breakpoint in _breakpoints) await InstallBreakpoint(breakpoint);
            BreakpointsGrid.Items.Refresh(); _starting = false;
            await gdb.ContinueAsync();
            CpuStatus.Text = T("SuperH target · GIII hardware profile", "SuperH 目标 · GIII 硬件配置");
            UpdateButtons();
        } catch { await StopDebug(); throw; }
        finally { _starting = false; }
    }
    private Task StopDebug()
    {
        if (_stopTask is { IsCompleted: false }) return _stopTask;
        _stopTask = StopDebugCore();
        return _stopTask;
    }
    private async Task StopDebugCore()
    {
        _stopping = true; _refreshVersion++;
        var gdb = _gdb; var emu = _emulator; var image = _debugImage;
        _gdb = null; _emulator = null; _debugImage = null;
        try {
            try { if (gdb != null) await gdb.DisposeAsync(); }
            finally { try { if (emu != null) await emu.DisposeAsync(); } finally { if (image != null) await image.DisposeAsync(); } }
        } finally {
            _executionFile = null; _executionLine = null; UpdateDecorations();
            _selectedFrame = null; _selectedFrameLevel = 0;
            LocalsGrid.ItemsSource = null; StackGrid.ItemsSource = null; RegistersGrid.ItemsSource = null; DisassemblyGrid.ItemsSource = null; MemoryText.Clear();
            foreach (var b in _breakpoints) { b.Number = ""; b.Status = "Pending build"; }
            foreach (var w in _watches) w.Value = "";
            BreakpointsGrid.Items.Refresh(); WatchGrid.Items.Refresh();
            CpuStatus.Text = T("Session stopped. Last screen retained.", "会话已停止，保留最后画面。");
            _stopping = false; UpdateButtons();
        }
    }
    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        if (_stopRequested) return;
        _stopRequested = true; _operationCancellation?.Cancel();
        try {
            if (_currentOperation is { } active) { try { await active; } catch { } }
            await StopDebug(); SetStatus(T("Stopped", "已停止"));
        } catch (Exception ex) { AppendOutput(ex.ToString()); }
        finally { _stopRequested = false; UpdateButtons(); }
    }
    private string? FindNativeGdb() => App.LaunchGdbOverride ?? (!string.IsNullOrWhiteSpace(App.Settings.GdbPath) ? App.Settings.GdbPath : new[] {
        Path.Combine(App.RootDirectory, "runtime", "gdb", "bin", "gdb.exe"),
        Path.Combine(App.RootDirectory, "runtime", "gdb", "bin", "sh-elf-gdb.exe"),
        Path.Combine(App.RootDirectory, "dist-toolchain", "native-gdb", "runtime", "gdb", "bin", "gdb.exe"),
        Path.Combine(App.RootDirectory, "dist-toolchain", "native-gdb", "bin", "sh-elf-gdb.exe")
    }.FirstOrDefault(File.Exists));
    private async void Restart_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { await StopDebug(); var a = _importedBuild ? _artifact! : await BuildProject(true); await StartDebug(a); });
    private async void Pause_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { if (_gdb?.State == DebugState.Running) await _gdb.PauseAsync(); });
    private async void Step_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { RequireStopped(); await _gdb!.StepAsync(); });
    private async void Next_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { RequireStopped(); await _gdb!.NextAsync(); });
    private async void Finish_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { RequireStopped(); await _gdb!.FinishAsync(); });
    private async void StepInstruction_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { RequireStopped(); await _gdb!.StepInstructionAsync(); });
    private async void NextInstruction_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { RequireStopped(); await _gdb!.NextInstructionAsync(); });
    private void RequireStopped() { if (!IsStopped) throw new InvalidOperationException(T("Pause the target before inspecting or changing its state.", "请先暂停目标程序，再检查或修改其状态。")); }
    private string TargetSource(string source)
    {
        if (_artifact == null) return source.Replace('\\', '/');
        foreach (var map in _artifact.SourceMappings.OrderByDescending(m => m.To.Length)) {
            var root = map.To.TrimEnd('\\', '/');
            if (source.Equals(root, StringComparison.OrdinalIgnoreCase)) return map.From;
            if (source.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || source.StartsWith(root + '/', StringComparison.OrdinalIgnoreCase))
                return map.From.TrimEnd('/') + "/" + Path.GetRelativePath(root, source).Replace('\\', '/');
        }
        return source.Replace('\\', '/');
    }
    private async Task InstallBreakpoint(SourceBreakpoint breakpoint)
    {
        if (_gdb == null) return;
        try {
            var remote = breakpoint.Expression.Length > 0
                ? await _gdb.InsertWatchpointAsync(breakpoint.Expression, breakpoint.Access)
                : await _gdb.InsertBreakpointAsync(_gdb.GetBreakpointLocation(breakpoint.File, breakpoint.Line), breakpoint.Condition);
            breakpoint.Number = remote.Number;
            breakpoint.Status = remote.Address == "<PENDING>" ? "Pending symbol" : "Verified";
            if (!breakpoint.Enabled) {
                try { await _gdb.SetBreakpointEnabledAsync(remote.Number, false); }
                catch { await _gdb.DeleteBreakpointAsync(remote.Number); throw; }
            }
        } catch (GdbCommandException ex) { breakpoint.Number = ""; breakpoint.Status = ex.Message; AppendOutput("Breakpoint: " + ex.Message); }
    }
    private async Task ToggleBreakpoint(string path, int line)
    {
        if (_gdb?.State == DebugState.Running) throw new InvalidOperationException(T("Pause before changing breakpoints.", "请先暂停，再修改断点。"));
        var existing = _breakpoints.FirstOrDefault(b => b.File.Equals(path, StringComparison.OrdinalIgnoreCase) && b.Line == line && b.Expression.Length == 0);
        if (existing != null) {
            if (_gdb != null && existing.Number.Length > 0) await _gdb.DeleteBreakpointAsync(existing.Number);
            _breakpoints.Remove(existing);
            if (_documents.TryGetValue(path, out var document)) document.BreakpointAnchors.Remove(existing);
        } else {
            var bp = new SourceBreakpoint { File = path, Line = line }; _breakpoints.Add(bp);
            if (_documents.TryGetValue(path, out var document)) TrackBreakpoint(document, bp);
            if (_gdb != null) await InstallBreakpoint(bp);
        }
        UpdateDecorations(); BreakpointsGrid.Items.Refresh(); SaveSessionState();
    }
    private async void Breakpoint_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { if (ActiveDocument is { } d) await ToggleBreakpoint(d.Path, d.Editor.TextArea.Caret.Line); });
    private async void RunTo_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        RequireStopped(); if (ActiveDocument is not { } d) return;
        await _gdb!.InsertBreakpointAsync(_gdb.GetBreakpointLocation(d.Path, d.Editor.TextArea.Caret.Line), temporary: true);
        await _gdb.ContinueAsync();
    });
    private async void RemoveBreakpoint_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        if (BreakpointsGrid.SelectedItem is not SourceBreakpoint bp) return;
        if (_gdb != null) { RequireStopped(); if (bp.Number.Length > 0) await _gdb.DeleteBreakpointAsync(bp.Number); }
        _breakpoints.Remove(bp); if (_documents.TryGetValue(bp.File, out var doc)) doc.BreakpointAnchors.Remove(bp); UpdateDecorations(); SaveSessionState();
    });
    private async void Condition_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        if (BreakpointsGrid.SelectedItem is not SourceBreakpoint bp) return;
        var values = Dialogs.Fields(this, T("Breakpoint condition", "断点条件"), (T("C/C++ expression (empty = unconditional)", "C/C++ 表达式（留空为无条件）"), bp.Condition));
        if (values == null) return;
        if (_gdb != null) { RequireStopped(); if (bp.Number.Length > 0) await _gdb.SetBreakpointConditionAsync(bp.Number, values[0]); }
        bp.Condition = values[0]; BreakpointsGrid.Items.Refresh(); SaveSessionState();
    });
    private async void ToggleEnabled_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        if (BreakpointsGrid.SelectedItem is not SourceBreakpoint bp) return;
        if (_gdb != null) {
            RequireStopped();
            if (bp.Number.Length > 0) await _gdb.SetBreakpointEnabledAsync(bp.Number, !bp.Enabled);
        }
        bp.Enabled = !bp.Enabled;
        BreakpointsGrid.Items.Refresh(); UpdateDecorations(); SaveSessionState();
    });
    private async void Watchpoint_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        var values = Dialogs.Fields(this, T("Data watchpoint", "数据监视点"), (T("Expression", "表达式"), "counter.value"), (T("Access: write / read / access", "类型：write / read / access"), "write"));
        if (values == null || string.IsNullOrWhiteSpace(values[0])) return;
        if (values[1] is not ("write" or "read" or "access")) throw new ArgumentException("write / read / access");
        if (_gdb != null) RequireStopped();
        var bp = new SourceBreakpoint { Expression = values[0], Access = values[1] }; _breakpoints.Add(bp);
        if (_gdb != null) await InstallBreakpoint(bp);
        BreakpointsGrid.Items.Refresh(); SaveSessionState();
    });

    private async Task RefreshDebug(bool navigate = true)
    {
        var gdb = _gdb;
        if (gdb == null || gdb.State != DebugState.Stopped) return;
        if (_refreshing) { _refreshPending = true; return; }
        _refreshing = true; var version = _refreshVersion;
        try {
            var frames = await gdb.GetStackAsync();
            if (_gdb != gdb || version != _refreshVersion) return;
            StackGrid.ItemsSource = frames;
            if (navigate) _selectedFrameLevel = 0;
            var frame = frames.FirstOrDefault(f => f.Level == _selectedFrameLevel) ?? frames.FirstOrDefault();
            _selectedFrame = frame;
            if (frame != null) {
                await gdb.SelectFrameAsync(frame.Level);
                if (_gdb != gdb || version != _refreshVersion) return;
                _selectedFrame = frame; _selectedFrameLevel = frame.Level; StackGrid.SelectedItem = frame;
            }
            if (navigate && frame != null) {
                _executionFile = frame.LocalPath != null && File.Exists(frame.LocalPath) ? Path.GetFullPath(frame.LocalPath) : frame.LocalPath;
                _executionLine = frame.Line;
                if (frame.LocalPath != null && File.Exists(frame.LocalPath)) OpenDocument(frame.LocalPath, frame.Line);
                UpdateDecorations();
                SetStatus(T("Paused", "已暂停") + $" · {frame.Function} · {frame.Address}");
                UpdateDebugPresentation();
            }
            // Missing library symbols must not prevent registers or the real screen from updating.
            async Task ReadSection(string name, Func<Task> read, Action clear) {
                try { await read(); }
                catch (Exception ex) { if (_gdb == gdb && version == _refreshVersion) { clear(); AppendOutput(name + ": " + ex.Message); } }
            }
            await ReadSection(T("Locals", "局部变量"), async () => { var value = await gdb.GetLocalsAsync(); if (_gdb == gdb && version == _refreshVersion) LocalsGrid.ItemsSource = value; }, () => LocalsGrid.ItemsSource = null);
            await ReadSection(T("Registers", "寄存器"), async () => { var value = await gdb.GetRegistersAsync(); if (_gdb == gdb && version == _refreshVersion) RegistersGrid.ItemsSource = value; }, () => RegistersGrid.ItemsSource = null);
            await ReadSection(T("Disassembly", "反汇编"), async () => { var value = await gdb.GetDisassemblyAsync("$pc", "$pc+40"); if (_gdb == gdb && version == _refreshVersion) DisassemblyGrid.ItemsSource = value; }, () => DisassemblyGrid.ItemsSource = null);
            if (_gdb != gdb || version != _refreshVersion) return;
            await RefreshWatches();
            ReadScreen(); UpdateButtons();
        } catch (Exception ex) { if (_gdb == gdb && version == _refreshVersion) AppendOutput("Inspect: " + ex.Message); }
        finally { _refreshing = false; UpdateButtons(); if (_refreshPending) { _refreshPending = false; if (IsStopped) await RefreshDebug(); } }
    }
    private async Task RefreshWatches()
    {
        var gdb = _gdb; if (gdb == null || !IsStopped) return;
        var version = _refreshVersion;
        foreach (var watch in _watches.ToArray()) {
            string value;
            try { value = await gdb.EvaluateAsync(watch.Expression); }
            catch (Exception ex) { value = ex.Message; }
            if (_gdb != gdb || _refreshVersion != version || !IsStopped) return;
            watch.Value = value;
        }
        if (_gdb == gdb && _refreshVersion == version && IsStopped) WatchGrid.Items.Refresh();
    }
    private async void AddWatch_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        var expression = WatchExpression.Text.Trim(); if (expression.Length == 0) return;
        if (!_watches.Any(w => w.Expression == expression)) _watches.Add(new WatchRow(expression));
        WatchExpression.Clear(); if (IsStopped) await RefreshWatches(); SaveSessionState();
    });
    private void WatchExpression_KeyDown(object sender, KeyEventArgs e) { if (e.Key == Key.Enter) { AddWatch_Click(sender, e); e.Handled = true; } }
    private void RemoveWatch_Click(object sender, RoutedEventArgs e) { if (WatchGrid.SelectedItem is WatchRow watch) { _watches.Remove(watch); SaveSessionState(); } }
    private async void EditWatch_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { if (WatchGrid.SelectedItem is WatchRow w) await EditExpression(w.Expression); });
    private async void EditLocal_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => { if (LocalsGrid.SelectedItem is DebugVariable v) await EditExpression(v.Name); });
    private async Task EditExpression(string expression)
    {
        RequireStopped(); var current = await _gdb!.EvaluateAsync(expression);
        var values = Dialogs.Fields(this, expression, (T("New value / expression", "新值 / 表达式"), current));
        if (values == null) return;
        await _gdb.EvaluateAsync($"({expression}) = ({values[0]})");
        await RefreshDebug(false);
    }
    private async void Stack_DoubleClick(object sender, MouseButtonEventArgs e) => await RunOperation(async () => {
        RequireStopped(); if (StackGrid.SelectedItem is not DebugFrame frame) return;
        await _gdb!.SelectFrameAsync(frame.Level);
        _selectedFrame = frame; _selectedFrameLevel = frame.Level;
        if (frame.LocalPath != null && File.Exists(frame.LocalPath)) OpenDocument(frame.LocalPath, frame.Line);
        LocalsGrid.ItemsSource = await _gdb.GetLocalsAsync(); await RefreshWatches();
        UpdateDebugPresentation();
    });
    private async void EditRegister_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        RequireStopped(); if (RegistersGrid.SelectedItem is not DebugRegister register) return;
        var values = Dialogs.Fields(this, register.Name, (T("New hexadecimal value", "新的十六进制值"), register.Value));
        if (values == null) return;
        await _gdb!.WriteRegisterAsync(register.Number, values[0]); await RefreshDebug();
    });
    private async void Memory_Click(object sender, RoutedEventArgs e) => await RunOperation(ReadMemory);
    private async Task ReadMemory()
    {
        RequireStopped();
        if (!int.TryParse(MemoryLength.Text, out var count) || count is < 1 or > 65536) throw new ArgumentException(T("Length must be 1–65536 bytes.", "长度须为 1–65536 字节。"));
        var address = MemoryAddress.Text.Trim();
        var bytes = await _gdb!.ReadMemoryAsync(address, count);
        var text = new StringBuilder();
        text.AppendLine(address);
        for (var i = 0; i < bytes.Length; i += 16) {
            var row = bytes.Skip(i).Take(16).ToArray();
            text.Append($"+{i:X6}  ").Append(string.Join(" ", row.Select(b => b.ToString("X2"))).PadRight(47)).Append("  ").AppendLine(new string(row.Select(b => b is >= 32 and < 127 ? (char)b : '.').ToArray()));
        }
        MemoryText.Text = text.ToString();
    }
    private async void WriteMemory_Click(object sender, RoutedEventArgs e) => await RunOperation(async () => {
        RequireStopped();
        var values = Dialogs.Fields(this, T("Write target memory", "写入目标内存"), (T("Address / expression", "地址 / 表达式"), MemoryAddress.Text), (T("Hex bytes, e.g. 00 00 00 01", "十六进制字节，如 00 00 00 01"), ""));
        if (values == null) return;
        var hex = string.Concat(values[1].Where(c => !char.IsWhiteSpace(c)));
        if (hex.Length > 8192) throw new ArgumentException("Maximum write: 4096 bytes.");
        await _gdb!.WriteMemoryAsync(values[0], Convert.FromHexString(hex));
        await ReadMemory(); await RefreshDebug(false);
    });
    private async Task InspectVariable(string expression)
    {
        RequireStopped(); var gdb = _gdb!;
        var root = await gdb.CreateVariableObjectAsync(expression);
        try {
            var tree = new TreeView { Margin = new Thickness(10) };
            async Task AddChildren(ItemsControl parent, DebugVariable variable) {
                if (variable.ObjectName == null) return;
                var children = await gdb.GetVariableChildrenAsync(variable.ObjectName);
                foreach (var child in children) {
                    var item = new TreeViewItem { Header = $"{child.Name} = {child.Value}   ({child.Type})", Tag = child };
                    parent.Items.Add(item);
                    if (child.Children > 0) {
                        item.Items.Add(new TreeViewItem());
                        item.Expanded += async (_, args) => {
                            if (!ReferenceEquals(args.OriginalSource, item) || item.Items.Count != 1 || (item.Items[0] as TreeViewItem)?.Tag != null) return;
                            item.Items.Clear(); try { await AddChildren(item, child); } catch (Exception ex) { item.Items.Add(new TreeViewItem { Header = ex.Message, Tag = "error" }); }
                        };
                    }
                }
            }
            var title = new TreeViewItem { Header = $"{expression} = {root.Value} ({root.Type})", IsExpanded = true }; tree.Items.Add(title);
            await AddChildren(title, root);
            var dialog = new Window { Owner = this, Title = expression, Width = 650, Height = 420, Content = tree, WindowStartupLocation = WindowStartupLocation.CenterOwner };
            dialog.ShowDialog();
        } finally { if (root.ObjectName != null && gdb.IsAlive) await gdb.DeleteVariableObjectAsync(root.ObjectName); }
    }
}
