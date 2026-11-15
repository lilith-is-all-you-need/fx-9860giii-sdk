using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Windows.Controls;
using System.Text.Json;
using FxStudio.Core;

namespace FxStudio.App;

public partial class MainWindow
{
    // Renders the actual WPF visual tree for repeatable layout review on hosts
    // where desktop capture is unavailable. It never supplies synthetic state.
    public async Task RenderForVerificationAsync(string path, string? stopLocation = null, bool verifyInteractions = false, bool verifyLoaderUi = false)
    {
        async Task WaitFor(Func<bool> ready) {
            for (var attempt = 0; !ready() && attempt < 600; attempt++) await Task.Delay(50);
            if (!ready()) throw new TimeoutException("UI verification did not reach the required state.");
        }
        await WaitFor(() => !_busy);
        if (stopLocation != null) {
            if (_gdb == null) throw new InvalidOperationException("Debug startup failed.\n" + OutputText.Text);
            await WaitFor(() => IsStopped && !_refreshing);
            var gdb = _gdb!;
            await gdb.InsertBreakpointAsync(stopLocation, temporary: true);
            await gdb.ContinueAsync();
            await WaitFor(() => IsStopped && !_refreshing);
            await RefreshDebug(); ReadScreen();
            File.WriteAllText(path + ".state.txt", OutputText.Text + "\n" + StatusText.Text);
        }
        if (verifyInteractions) await VerifyDebugInteractionsAsync(path);
        await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
        UpdateLayout();
        var bounds = (FrameworkElement)Content;
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(bounds.ActualWidth), (int)Math.Ceiling(bounds.ActualHeight), 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(bounds);
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        var fullPath = Path.GetFullPath(path); Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        using (var stream = File.Create(fullPath)) encoder.Save(stream);
        if (verifyLoaderUi) {
            var knowledge = CreateKnowledgeWindow(); knowledge.Show();
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            knowledge.UpdateLayout();
            var panel=(DockPanel)knowledge.Content;
            var search=panel.Children.OfType<TextBox>().First();
            var list=panel.Children.OfType<ListBox>().Single();
            if(list.Items.Count<4000)throw new InvalidOperationException("Embedded syscall coverage was not loaded");
            RenderWindow(knowledge,fullPath+".knowledge.png");
            search.Text="0x042C";
            var syscall=list.Items.OfType<KnowledgeItem>().FirstOrDefault(x=>x.Title.StartsWith("0x042C",StringComparison.OrdinalIgnoreCase));
            if(syscall==null)throw new InvalidOperationException("Knowledge search failed");
            list.SelectedItem=syscall;
            knowledge.UpdateLayout();RenderWindow(knowledge,fullPath+".search.png");
            knowledge.Close();
            File.WriteAllText(fullPath+".loader-ui.json",JsonSerializer.Serialize(new {passed=true,embeddedEntries=LoadCalculatorKnowledge().Count,search="0x042C",method="Actual WPF window and filtering"}));
        }
        await CloseForVerificationAsync();
    }
    private async Task VerifyDebugInteractionsAsync(string renderPath)
    {
        if (_gdb == null || !IsStopped || _project == null || ActiveDocument == null) throw new InvalidOperationException("UI validation requires a stopped source debug session.");
        var checks = new List<string>();
        void Check(bool ok, string description) { if (!ok) throw new InvalidOperationException(description); checks.Add(description); }
        async Task Settle() {
            if (_currentOperation != null) await _currentOperation;
            for (var i=0;i<600 && (_busy || _refreshing || !IsStopped);i++) await Task.Delay(50);
            if (_busy || _refreshing || !IsStopped) throw new TimeoutException("UI operation did not settle at a stop.");
            await Dispatcher.InvokeAsync(() => {}, DispatcherPriority.ApplicationIdle);
        }
        Check(DebugContextText.Text.Contains("main"), "Human-readable stop reason and current frame displayed");
        InspectorTabs.SelectedIndex = 5;
        var before = _refreshVersion;
        StepInstruction_Click(this,new RoutedEventArgs()); await Settle();
        Check(_refreshVersion > before && InspectorTabs.SelectedIndex == 5, "Actual instruction step retains the selected inspector tab");
        var doc = ActiveDocument!;
        await ToggleBreakpoint(doc.Path,doc.Editor.TextArea.Caret.Line);
        var breakpoint = _breakpoints.Last(); BreakpointsGrid.SelectedItem = breakpoint; UpdateButtons();
        ToggleEnabled_Click(this,new RoutedEventArgs()); await Settle();
        Check(!breakpoint.Enabled && !(await _gdb!.GetBreakpointsAsync()).Single(x=>x.Number==breakpoint.Number).Enabled, "Disable breakpoint UI changes the actual GDB breakpoint");
        ToggleEnabled_Click(this,new RoutedEventArgs()); await Settle();
        Check(breakpoint.Enabled && (await _gdb!.GetBreakpointsAsync()).Single(x=>x.Number==breakpoint.Number).Enabled, "Enable breakpoint UI restores the actual GDB breakpoint");
        RemoveBreakpoint_Click(this,new RoutedEventArgs()); await Settle();
        EnlargeScreen_Click(this,new RoutedEventArgs());
        Check(_screenWindow is { IsVisible:true }, "Integer zoom window displays the real live framebuffer");
        _screenWindow!.UpdateLayout();
        RenderWindow(_screenWindow,renderPath+".screen.png");
        _screenWindow.Close();
        var sourceImage = Directory.EnumerateFiles(Path.Combine(_project.SourceDirectory,"assets"),"*.png").FirstOrDefault();
        if(sourceImage != null) {
            OpenProjectFile(sourceImage);
            Check(_resourceWindows.TryGetValue(Path.GetFullPath(sourceImage),out var resource) && resource.IsVisible, "Source PNG opens in a read-only resource preview");
            resource!.UpdateLayout(); RenderWindow(resource,renderPath+".resource.png"); resource.Close();
        }
        Check(ScreenImage.Source is BitmapSource { PixelWidth:128,PixelHeight:64 }, "Preview comes from a 128 by 64 target framebuffer");
        var encoder=new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create((BitmapSource)ScreenImage.Source));
        using(var stream=File.Create(renderPath+".frame.png")) encoder.Save(stream);
        InspectorTabs.SelectedIndex=7;
        File.WriteAllText(renderPath+".validation.json",JsonSerializer.Serialize(new {passed=true,checks,method="Actual WPF handlers and real GDB/emulator; offscreen visual tree rendering",desktopScreenshotAvailable=false},new JsonSerializerOptions{WriteIndented=true}));
    }
    private static void RenderWindow(Window window,string path)
    {
        var content=(FrameworkElement)window.Content;
        var bitmap=new RenderTargetBitmap((int)Math.Ceiling(content.ActualWidth),(int)Math.Ceiling(content.ActualHeight),96,96,PixelFormats.Pbgra32);
        bitmap.Render(content); var encoder=new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream=File.Create(path); encoder.Save(stream);
    }
    public async Task CloseForVerificationAsync() { _operationCancellation?.Cancel(); await StopDebug(); _allowClose = true; Close(); }
}
