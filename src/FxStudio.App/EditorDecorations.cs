using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using ICSharpCode.AvalonEdit.Editing;
using ICSharpCode.AvalonEdit.Rendering;

namespace FxStudio.App;

internal sealed class BreakpointMargin(Func<int, bool?> breakpointState, Action<int> toggle, Func<int?> currentLine) : AbstractMargin
{
    protected override Size MeasureOverride(Size availableSize) => new(23, 0);
    protected override void OnRender(DrawingContext dc)
    {
        dc.DrawRectangle(new SolidColorBrush(Color.FromRgb(247, 249, 250)), null, new Rect(RenderSize));
        if (TextView is not { VisualLinesValid: true }) return;
        foreach (var line in TextView.VisualLines) {
            var number = line.FirstDocumentLine.LineNumber;
            var y = line.VisualTop - TextView.ScrollOffset.Y + Math.Min(line.Height, 19) / 2;
            if (breakpointState(number) is { } enabled)
                dc.DrawEllipse(enabled ? Brushes.IndianRed : Brushes.Transparent, new Pen(enabled ? Brushes.IndianRed : Brushes.Gray, 1.5), new Point(10, y), 5, 5);
            if (currentLine() == number) {
                var arrow = new StreamGeometry();
                using (var ctx = arrow.Open()) { ctx.BeginFigure(new Point(2, y-6), true, true); ctx.LineTo(new Point(18, y), true, false); ctx.LineTo(new Point(2, y+6), true, false); }
                dc.DrawGeometry(Brushes.DarkGoldenrod, null, arrow);
            }
        }
    }
    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonDown(e);
        if (TextView is not { VisualLinesValid: true }) return;
        var y = e.GetPosition(this).Y + TextView.ScrollOffset.Y;
        var line = TextView.VisualLines.FirstOrDefault(v => y >= v.VisualTop && y < v.VisualTop + v.Height);
        if (line != null) { toggle(line.FirstDocumentLine.LineNumber); e.Handled = true; }
    }
    protected override void OnTextViewChanged(TextView oldView, TextView newView)
    {
        if (oldView != null) oldView.VisualLinesChanged -= Changed;
        base.OnTextViewChanged(oldView, newView);
        if (newView != null) newView.VisualLinesChanged += Changed;
    }
    private void Changed(object? sender, EventArgs e) => InvalidateVisual();
}

internal sealed class ExecutionRenderer(Func<int?> lineNumber) : IBackgroundRenderer
{
    public KnownLayer Layer => KnownLayer.Background;
    public void Draw(TextView textView, DrawingContext dc)
    {
        var n = lineNumber();
        if (n is null || textView.Document == null || n < 1 || n > textView.Document.LineCount) return;
        foreach (var rect in BackgroundGeometryBuilder.GetRectsForSegment(textView, textView.Document.GetLineByNumber(n.Value)))
            dc.DrawRectangle(new SolidColorBrush(Color.FromRgb(255, 245, 201)), null, new Rect(0, rect.Y, textView.ActualWidth, rect.Height));
    }
}
