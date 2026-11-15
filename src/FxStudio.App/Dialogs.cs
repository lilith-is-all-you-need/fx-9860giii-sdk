using System.Windows;
using System.Windows.Controls;

namespace FxStudio.App;

internal static class Dialogs
{
    public static string[]? Fields(Window owner, string title, params (string label, string value)[] fields)
    {
        var panel = new StackPanel { Margin = new Thickness(22) };
        var boxes = new List<TextBox>();
        foreach (var (label, value) in fields) {
            panel.Children.Add(new TextBlock { Text = label, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 10, 0, 5) });
            var box = new TextBox { Text = value, MinWidth = 420, Margin = new Thickness(0, 0, 0, 4) };
            panel.Children.Add(box); boxes.Add(box);
        }
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 18, 0, 0) };
        var ok = new Button { Content = "OK", IsDefault = true, MinWidth = 85 };
        var cancel = new Button { Content = Language.Text("Cancel", "取消"), IsCancel = true, MinWidth = 85 };
        buttons.Children.Add(ok); buttons.Children.Add(cancel); panel.Children.Add(buttons);
        var window = new Window { Owner = owner, Title = title, Content = panel, SizeToContent = SizeToContent.WidthAndHeight, WindowStartupLocation = WindowStartupLocation.CenterOwner, ResizeMode = ResizeMode.NoResize, MaxWidth = 760 };
        ok.Click += (_, _) => window.DialogResult = true;
        window.Loaded += (_, _) => { boxes.FirstOrDefault()?.Focus(); boxes.FirstOrDefault()?.SelectAll(); };
        return window.ShowDialog() == true ? boxes.Select(b => b.Text).ToArray() : null;
    }
}
