using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using FxStudio.Core;
using Microsoft.Win32;

namespace FxStudio.App;

public partial class MainWindow
{
    private static string DescribeStop(MiRecord? stop)
    {
        var reason = stop?.GetString("reason");
        return reason switch {
            "breakpoint-hit" => T("Breakpoint reached", "命中断点") + (stop?.GetString("bkptno") is { } number ? " #" + number : ""),
            "watchpoint-trigger" => T("Watched value changed", "监视的值发生变化"),
            "read-watchpoint-trigger" => T("Watched memory was read", "监视的内存被读取"),
            "access-watchpoint-trigger" => T("Watched memory was accessed", "监视的内存被访问"),
            "end-stepping-range" => T("Step completed", "单步完成"),
            "function-finished" => T("Function returned", "函数已返回"),
            "location-reached" => T("Requested location reached", "已到达指定位置"),
            "signal-received" when stop?.GetString("signal-name") == "SIGINT" => T("Execution paused", "执行已暂停"),
            "signal-received" => T("Target signal", "目标信号") + ": " + stop?.GetString("signal-name") + " · " + stop?.GetString("signal-meaning"),
            "exited-normally" => T("Program exited normally", "程序正常退出"),
            "exited" => T("Program exited", "程序已退出") + " · " + stop?.GetString("exit-code"),
            null or "" or "stopped" => T("Execution paused", "执行已暂停"),
            _ => T("Execution stopped", "执行停止") + " · " + reason
        };
    }

    private void UpdateDebugPresentation()
    {
        var state = _gdb?.State;
        var text = state switch {
            DebugState.Running => T("Running", "正在运行"),
            DebugState.Stopped => T("Paused", "已暂停"),
            DebugState.Starting => T("Connecting", "正在连接"),
            DebugState.Faulted => T("Debugger error", "调试器错误"),
            DebugState.Exited or DebugState.Disposed => T("Ended", "已结束"),
            _ => _starting ? T("Starting", "正在启动") : T("Offline workspace", "离线工作区")
        };
        ConnectionText.Text = _gdb != null ? "SUPERH · " + text : text;
        if (state == DebugState.Running) {
            DebugContextText.Text = T("Running · displayed variables are from the last pause. Pause to inspect current values.", "正在运行 · 显示的是上次暂停时的变量；暂停后可检查当前值。");
            CpuStatus.Text = T("Running · screen and keys are live.", "正在运行 · 屏幕与按键实时联动。");
        } else if (state == DebugState.Stopped) {
            var reason = DescribeStop(_gdb?.LastStop);
            var frame = _selectedFrame;
            var location = frame == null ? T("Reading stack…", "正在读取调用栈…") : $"#{frame.Level}  {frame.Function}";
            if (frame?.LocalPath is { } path && File.Exists(path)) location += $" · {Path.GetFileName(path)}:{frame.Line}";
            else if (frame != null) location += T(" · source unavailable; use Disassembly", " · 源码不可用，可查看反汇编");
            DebugContextText.Text = reason + " · " + location;
            CpuStatus.Text = reason + "\nPC " + (_gdb?.GetStoppedFrame()?.Address ?? frame?.Address ?? "—");
        } else {
            DebugContextText.Text = T("Double-click a paused variable to inspect members. Double-click a stack frame to inspect that call.", "暂停后双击变量查看成员；双击调用栈中的栈帧可检查该次调用。");
        }
    }

    private void EnlargeScreen_Click(object sender, RoutedEventArgs e)
    {
        if (ScreenImage.Source is not BitmapSource bitmap) return;
        if (_screenWindow != null) { _screenWindow.Activate(); return; }
        var image = new Image { Stretch = Stretch.Fill, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        image.SetBinding(Image.SourceProperty, new Binding(nameof(Image.Source)) { Source = ScreenImage });
        RenderOptions.SetBitmapScalingMode(image, BitmapScalingMode.NearestNeighbor);
        var zoom = new ComboBox { Width = 85, Margin = new Thickness(5), ItemsSource = new[] { "1×", "2×", "3×", "4×", "6×", "8×" }, SelectedIndex = 3 };
        var scales = new[] { 1, 2, 3, 4, 6, 8 };
        void ApplyZoom() { var scale = scales[Math.Max(0, zoom.SelectedIndex)]; image.Width = bitmap.PixelWidth * scale; image.Height = bitmap.PixelHeight * scale; }
        zoom.SelectionChanged += (_, _) => ApplyZoom(); ApplyZoom();
        var save = new Button { Content = T("Save PNG…", "保存 PNG…"), Margin = new Thickness(5) };
        save.Click += SaveScreen_Click;
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(7) };
        toolbar.Children.Add(new TextBlock { Text = T("Zoom", "缩放"), VerticalAlignment = VerticalAlignment.Center });
        toolbar.Children.Add(zoom); toolbar.Children.Add(save);
        var hint = new TextBlock { Text = T("Live framebuffer · PNG saves the original resolution.", "实时屏幕缓冲区 · PNG 保存原始分辨率。"), Margin = new Thickness(12, 4, 12, 10), TextWrapping = TextWrapping.Wrap };
        var panel = new DockPanel { Background = new SolidColorBrush(Color.FromRgb(243,245,247)) }; DockPanel.SetDock(toolbar, Dock.Top); panel.Children.Add(toolbar); DockPanel.SetDock(hint, Dock.Bottom); panel.Children.Add(hint);
        panel.Children.Add(new ScrollViewer { Content = image, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Background = new SolidColorBrush(Color.FromRgb(199, 211, 197)), Padding = new Thickness(12) });
        _screenWindow = new Window { Owner = this, Title = T("Calculator screen", "计算器画面"), Width = 600, Height = 420, MinWidth = 300, MinHeight = 230, Content = panel, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        _screenWindow.Closed += (_, _) => _screenWindow = null;
        _screenWindow.Show();
    }

    private async void SaveScreen_Click(object sender, RoutedEventArgs e) => await RunOperation(() => {
        // Capture the displayed frame before opening the dialog, even if execution continues.
        if (ScreenImage.Source is not BitmapSource bitmap) return Task.CompletedTask;
        var dialog = new SaveFileDialog { Title = T("Save calculator screen", "保存计算器画面"), Filter = "PNG image (*.png)|*.png", DefaultExt = ".png", AddExtension = true, FileName = "fx-screen-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".png" };
        if (dialog.ShowDialog(this) != true) return Task.CompletedTask;
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        var temporary = dialog.FileName + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { using (var file = File.Create(temporary)) encoder.Save(file); File.Move(temporary, dialog.FileName, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
        SetStatus(T("Saved screen", "已保存画面") + $" · {bitmap.PixelWidth} × {bitmap.PixelHeight} · " + dialog.FileName);
        return Task.CompletedTask;
    });
}
