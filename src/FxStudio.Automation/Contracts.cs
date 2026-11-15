namespace FxStudio.Automation;

public sealed record CommandDefinition(string Name, int Version, string Description, string Effect, object InputSchema);
public sealed record AutomationEvent(string? SessionId, string Kind, object? Data);
public sealed class AutomationException(string code, string message, bool retryable = false) : Exception(message)
{
    public string Code { get; } = code;
    public bool Retryable { get; } = retryable;
}
public sealed record FrameInfo(int Level, string Address, string Function, string? File, string? SourcePath, int? Line);
public sealed record StopInfo(string? Reason, string? BreakpointNumber, string? SignalName, string? SignalMeaning,
    FrameInfo? Frame, long Revision, DateTimeOffset Timestamp);
public sealed record VariableInfo(string Name, string? Value, string? Type, int? Children, bool IsArgument);
public sealed record BreakpointInfo(string Number, string? Type, bool Enabled, string? Address, string? File, int? Line, string? Condition);
public sealed record ArtifactInfo(string ElfPath, string G1APath, string ManifestPath, string Configuration, string? ElfSha256, string? G1ASha256, long? G1ABytes);
public sealed record SessionInfo(string SessionId, string Name, string ProjectPath, string SourceDirectory, string BuildDirectory,
    string SdkPath, string State, long Revision, bool Busy, int SelectedFrame, StopInfo? LastStop, ArtifactInfo? Artifact);
public sealed record DiagnosticInfo(string Severity, string Message, string? File, int? Line, int? Column);
public sealed record SectionError(string Section, string Code, string Message, bool Retryable = false);
public sealed record EvaluationInfo(string Expression, string? Value, SectionError? Error);
public sealed record ScreenInfo(string Path, string Sha256, string MimeType, string Base64Bmp, int Width, int Height, int Bytes);
public sealed record SnapshotInfo(string SessionId, long Revision, string State, bool Consistent, int SelectedFrame,
    StopInfo? LastStop, string? Reason, IReadOnlyList<FrameInfo>? Frames, IReadOnlyList<VariableInfo>? Locals,
    object? Registers, IReadOnlyList<BreakpointInfo>? Breakpoints, ScreenInfo? Screen,
    IReadOnlyList<EvaluationInfo>? Expressions, IReadOnlyList<SectionError> Errors, System.Text.Json.JsonElement? TargetStatus);
