using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace FxStudio.App;

public partial class MainWindow
{
    internal sealed record KnowledgeItem(string Title, string Evidence, string Text, string Source)
    {
        public override string ToString() => Title;
    }

    internal static IReadOnlyList<KnowledgeItem> LoadCalculatorKnowledge()
    {
        var assembly = Assembly.GetExecutingAssembly();
        using var knowledge = assembly.GetManifestResourceStream("FxStudio.CalculatorKnowledge.json")!;
        var items = JsonSerializer.Deserialize<List<KnowledgeItem>>(knowledge)!;
        using var coverage = assembly.GetManifestResourceStream("FxStudio.SyscallCoverage.json")!;
        using var document = JsonDocument.Parse(coverage);
        foreach (var entry in document.RootElement.GetProperty("entries").EnumerateArray()) {
            var number = entry.GetProperty("number").GetString()!;
            var status = entry.GetProperty("status").GetString()!;
            var name = entry.TryGetProperty("name", out var n) ? n.GetString() : "未记录名称";
            items.Add(new($"{number} · {name}", status, entry.ToString(), "probes/emulator/syscall-coverage.json"));
        }
        return items;
    }

    private void CalculatorKnowledge_Click(object sender, RoutedEventArgs e) => CreateKnowledgeWindow().Show();

    internal Window CreateKnowledgeWindow()
    {
        var items = LoadCalculatorKnowledge();
        var panel = new DockPanel { Margin = new Thickness(20), Background = System.Windows.Media.Brushes.WhiteSmoke };
        var heading = new TextBlock { Text = T("Calculator reference · evidence and emulator limits", "计算器资料 · 实机证据、固件分析与模拟器限制"), FontSize = 18, Margin = new Thickness(0,0,0,10) };
        DockPanel.SetDock(heading, Dock.Top); panel.Children.Add(heading);
        var search = new TextBox { ToolTip = T("Search topic, address or syscall", "搜索主题、地址或系统调用"), Margin = new Thickness(0,0,0,12) };
        DockPanel.SetDock(search, Dock.Top); panel.Children.Add(search);
        var list = new ListBox { Width = 320, ItemsSource = items };
        DockPanel.SetDock(list, Dock.Left); panel.Children.Add(list);
        var detail = new TextBox { IsReadOnly = true, TextWrapping = TextWrapping.Wrap, VerticalContentAlignment = VerticalAlignment.Top, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(14,0,0,0), Padding = new Thickness(12) };
        panel.Children.Add(detail);
        list.SelectionChanged += (_,_) => { if (list.SelectedItem is KnowledgeItem item) detail.Text = $"{item.Title}\n\n证据：{item.Evidence}\n\n{item.Text}\n\n来源：{item.Source}"; };
        search.TextChanged += (_,_) => {
            var q=search.Text.Trim(); list.ItemsSource=items.Where(x=>$"{x.Title} {x.Text} {x.Evidence}".Contains(q,StringComparison.OrdinalIgnoreCase)).ToList();
            list.SelectedIndex=0;
        };
        list.SelectedIndex=0;
        return new Window { Owner=this, Title=T("Calculator reference","计算器资料"), Width=950, Height=650, MinWidth=720, MinHeight=400, Content=panel, WindowStartupLocation=WindowStartupLocation.CenterOwner };
    }

    private void PrepareAddin_Click(object sender, RoutedEventArgs e)
    {
        var studio = Path.Combine(App.RootDirectory,"ProfileStudio","ProfileStudio.exe");
        if(File.Exists(studio)) {
            try { Process.Start(new ProcessStartInfo(studio){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(studio)!}); }
            catch(Exception ex) { MessageBox.Show(this,ex.Message,"FX Profile Studio"); }
            return;
        }
        var source = new OpenFileDialog { Filter="G1A / BIN|*.g1a;*.bin", Multiselect=false };
        if(source.ShowDialog(this)!=true)return;
        var parent = new OpenFolderDialog { Title=T("Choose output parent folder", "选择输出目录的父文件夹") };
        if(parent.ShowDialog(this)!=true)return;
        var output = parent.FolderName;
        var script = Path.Combine(App.RootDirectory,"tooling","profile_job.py");
        var python = Path.Combine(App.RootDirectory,"sdk","native","host","python","python.exe");
        if(!File.Exists(script)||!File.Exists(python)) { MessageBox.Show(this,T("The Loader suite is missing from this package.","此安装包缺少 Loader 工具，请安装完整套件。"),"Fx Studio"); return; }
        var panel=new StackPanel { Margin=new Thickness(20) };
        panel.Children.Add(new TextBlock { Text=source.FileName,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,0,12) });
        panel.Children.Add(new TextBlock { Text=T("Loading method", "加载方式") });
        var mode=new ComboBox { ItemsSource=new[]{"auto","flash","ram","mapped","extended"},SelectedIndex=0,Margin=new Thickness(0,5,0,12) };panel.Children.Add(mode);
        var hint=new TextBlock { Text=T("Auto prepares ordinary G1As with the generic Flash loader. Unsupported structures receive a report; generated bundles still need device testing.","自动模式为普通 G1A 准备通用 Flash 加载包，不依赖程序名单。不支持的结构会列出原因；生成测试包仍需实机验证。"),TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,0,12) };panel.Children.Add(hint);
        var attach=new CheckBox { Content=T("Include the shared Loader", "同时导出公共 Loader"),IsChecked=false,Margin=new Thickness(0,0,0,6) };panel.Children.Add(attach);
        var result=new TextBox { IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Height=210,Margin=new Thickness(0,12,0,10) };panel.Children.Add(result);
        var run=new Button { Content=T("Prepare files","分析并准备文件"),HorizontalAlignment=HorizontalAlignment.Left };panel.Children.Add(run);
        var reveal=new Button { Content=T("Open result folder","打开结果目录"),HorizontalAlignment=HorizontalAlignment.Left,IsEnabled=false };panel.Children.Add(reveal);
        var window=new Window { Owner=this,Title=T("Prepare G1A for Loader","为 Loader 准备 G1A"),Width=700,SizeToContent=SizeToContent.Height,Content=panel,WindowStartupLocation=WindowStartupLocation.CenterOwner };
        using var cancel=new CancellationTokenSource();
        window.Closed+=(_,_)=>cancel.Cancel();
        reveal.Click+=(_,_)=>Process.Start(new ProcessStartInfo(output){UseShellExecute=true});
        run.Click+=async(_,_)=>{
            run.IsEnabled=false;mode.IsEnabled=false;attach.IsEnabled=false;result.Text=T("Analyzing…","正在分析…");
            try {
                var start=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
                foreach(var arg in new[]{"-X","utf8",script,"generate","--input",source.FileName,"--output-root",parent.FolderName,"--backend",(string)mode.SelectedItem})start.ArgumentList.Add(arg);
                if(attach.IsChecked==true)start.ArgumentList.Add("--include-loader");
                using var process=Process.Start(start) ?? throw new IOException("Unable to start offline analyzer");
                using var registration=cancel.Token.Register(()=>{try{if(!process.HasExited)process.Kill(true);}catch(InvalidOperationException){} });
                var stdout=process.StandardOutput.ReadToEndAsync(cancel.Token);var stderr=process.StandardError.ReadToEndAsync(cancel.Token);
                await process.WaitForExitAsync(cancel.Token);
                var text=await stdout;
                foreach(var line in text.Split('\n',StringSplitOptions.RemoveEmptyEntries)) {
                    try { using var doc=JsonDocument.Parse(line); if(doc.RootElement.TryGetProperty("result",out var r) && r.TryGetProperty("output",out var path))output=path.GetString()??output; }
                    catch(JsonException) { }
                }
                result.Text=(process.ExitCode==0?T("Program folder prepared. Use it with the shared Loader; hardware validation remains necessary.","程序目录已生成，配合公共 Loader 使用；仍需实机验证。") : process.ExitCode==2?T("Analysis completed; runtime adaptation is required.","分析完成；仍需运行时适配。") : T("Preparation failed.","准备失败。"))+"\n\n"+text+"\n"+await stderr;
                reveal.IsEnabled=Directory.Exists(output);
            } catch(OperationCanceledException) { } catch(Exception ex) { result.Text=ex.Message; }
        };
        window.ShowDialog();
    }
}
