using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace FxStudio.App;

public partial class MainWindow
{
    private static readonly HashSet<string> TextExtensions = new(StringComparer.OrdinalIgnoreCase) {
        ".c", ".h", ".cpp", ".hpp", ".cxx", ".hxx", ".cc", ".hh", ".s", ".asm", ".inc", ".in", ".ipp", ".tpp",
        ".cmake", ".txt", ".json", ".md", ".rst", ".html", ".css", ".js", ".py", ".ps1", ".sh", ".bat", ".cmd",
        ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml", ".xml", ".csv", ".ld", ".lds", ".mak", ".mk", ".log", ".map", ".d", ".fxconv"
    };
    private static readonly HashSet<string> TextNames = new(StringComparer.OrdinalIgnoreCase) {
        "Makefile", "GNUmakefile", "LICENSE", "COPYING", "README", "fxconv-metadata.txt", "fxconv-metadata", ".gitignore", ".gitattributes", ".editorconfig"
    };
    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase) { ".png", ".bmp", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".ico" };
    private readonly Dictionary<string, Window> _resourceWindows = new(StringComparer.OrdinalIgnoreCase);

    private static bool IsTextDocument(string path) => TextExtensions.Contains(Path.GetExtension(path)) || TextNames.Contains(Path.GetFileName(path));

    private void OpenProjectFile(string path)
    {
        if (IsTextDocument(path)) { OpenDocument(path); return; }
        path = Path.GetFullPath(path);
        if (_resourceWindows.TryGetValue(path, out var existing)) { existing.Activate(); return; }
        if (ImageExtensions.Contains(Path.GetExtension(path))) OpenImageResource(path);
        else {
            var file = new FileInfo(path);
            var text = new TextBox {
                Text = T("Read-only resource information", "只读资源信息") + "\n\n" + path + "\n\n" + T("Size", "大小") + $": {file.Length:N0} " + T("bytes", "字节") + "\n\n" +
                    T("This file type has no built-in preview. It is not opened as editable text. Converted objects, fonts and compressed data require their corresponding format tools.", "此文件类型暂不支持内置预览，不会作为可保存文本打开。转换后的目标文件、字体和压缩数据需要对应格式工具查看。"),
                IsReadOnly = true, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(16), VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            };
            ShowResourceWindow(path, text, 650, 300);
        }
    }

    private void OpenImageResource(string path)
    {
        if (new FileInfo(path).Length > 64L * 1024 * 1024) throw new IOException(T("Image preview accepts files up to 64 MiB.", "图片预览接受最大 64 MiB 的文件。"));
        BitmapFrame bitmap;
        int frameCount;
        using (var stream = File.OpenRead(path)) {
            var metadata = BitmapDecoder.Create(stream, BitmapCreateOptions.DelayCreation, BitmapCacheOption.OnDemand);
            var first = metadata.Frames[0]; frameCount = metadata.Frames.Count;
            if ((long)first.PixelWidth * first.PixelHeight > 16_000_000) throw new IOException(T("Image preview accepts up to 16 million pixels.", "图片预览接受最大 1600 万像素。"));
            // Copy only the first frame, so a multi-frame image cannot retain the file or decode every frame.
            var stride = checked((first.PixelWidth * first.Format.BitsPerPixel + 7) / 8);
            var bytes = checked((long)stride * first.PixelHeight);
            if (bytes > 128L * 1024 * 1024) throw new IOException(T("Decoded image is too large for the preview.", "解码后的图片过大，无法预览。"));
            var pixels = new byte[checked((int)bytes)];
            first.CopyPixels(pixels, stride, 0);
            bitmap = BitmapFrame.Create(BitmapSource.Create(first.PixelWidth, first.PixelHeight, 96, 96, first.Format, first.Palette, pixels, stride));
            bitmap.Freeze();
        }
        var image = new Image { Source = bitmap, Stretch = Stretch.Fill, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        RenderOptions.SetBitmapScalingMode(image, BitmapScalingMode.NearestNeighbor);
        var scales = new[] { 1, 2, 3, 4, 6, 8 };
        var zoom = new ComboBox { Width = 85, ItemsSource = scales.Select(x => x + "×").ToArray(), SelectedIndex = bitmap.PixelWidth <= 128 && bitmap.PixelHeight <= 64 ? 3 : 0, Margin = new Thickness(8, 0, 0, 0) };
        void ApplyZoom() { var scale = scales[Math.Max(0, zoom.SelectedIndex)]; image.Width = bitmap.PixelWidth * scale; image.Height = bitmap.PixelHeight * scale; }
        zoom.SelectionChanged += (_, _) => ApplyZoom(); ApplyZoom();
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(12) };
        toolbar.Children.Add(new TextBlock { Text = $"{bitmap.PixelWidth} × {bitmap.PixelHeight} px · {new FileInfo(path).Length:N0} " + T("bytes", "字节"), VerticalAlignment = VerticalAlignment.Center });
        toolbar.Children.Add(zoom);
        var hint = new TextBlock {
            Text = T("Source image preview · transparency uses a checkerboard. This is not an fxconv output preview.", "源图片预览 · 棋盘格表示透明区域；这里不是 fxconv 转换结果预览。") +
                (frameCount > 1 ? T($" First frame only ({frameCount} frames).", $" 仅显示首帧（共 {frameCount} 帧）。") : ""),
            TextWrapping = TextWrapping.Wrap, Margin = new Thickness(12, 8, 12, 12)
        };
        var checker = new DrawingGroup();
        checker.Children.Add(new GeometryDrawing(Brushes.White, null, new RectangleGeometry(new Rect(0, 0, 16, 16))));
        checker.Children.Add(new GeometryDrawing(new SolidColorBrush(Color.FromRgb(224, 228, 232)), null, new RectangleGeometry(new Rect(0, 0, 8, 8))));
        checker.Children.Add(new GeometryDrawing(new SolidColorBrush(Color.FromRgb(224, 228, 232)), null, new RectangleGeometry(new Rect(8, 8, 8, 8))));
        var background = new DrawingBrush(checker) { TileMode = TileMode.Tile, Viewport = new Rect(0, 0, 16, 16), ViewportUnits = BrushMappingMode.Absolute };
        background.Freeze();
        var content = new DockPanel { Background = new SolidColorBrush(Color.FromRgb(243,245,247)) }; DockPanel.SetDock(toolbar, Dock.Top); content.Children.Add(toolbar); DockPanel.SetDock(hint, Dock.Bottom); content.Children.Add(hint);
        content.Children.Add(new ScrollViewer { Content = image, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Background = background, Padding = new Thickness(12) });
        ShowResourceWindow(path, content, 700, 500);
    }

    private void ShowResourceWindow(string path, object content, double width, double height)
    {
        var window = new Window { Owner = this, Title = T("Resource", "资源") + " · " + Path.GetFileName(path), Content = content, Width = width, Height = height, MinWidth = 330, MinHeight = 230, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        _resourceWindows.Add(path, window);
        window.Closed += (_, _) => _resourceWindows.Remove(path);
        window.Show();
    }
}
