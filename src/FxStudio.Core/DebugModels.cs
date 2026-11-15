namespace FxStudio.Core;

public enum DebugState { NotStarted, Starting, Stopped, Running, Exited, Faulted, Disposed }
public sealed record SourceMapping(string From, string To);

public sealed record GdbLaunchOptions
{
    public required string ExecutablePath { get; init; }
    public IReadOnlyList<string> Arguments { get; init; } = ["--interpreter=mi2", "--quiet", "--nx"];
    public required string ElfPath { get; init; }
    public required int Port { get; init; }
    public string? WorkingDirectory { get; init; }
    public string Architecture { get; init; } = "sh4al-dsp";
    public string Endian { get; init; } = "big";
    public IReadOnlyList<SourceMapping> GdbSourceMappings { get; init; } = [];
    public IReadOnlyList<SourceMapping> SourceMappings { get; init; } = [];
    /// <summary>DWARF roots to prefer when several source paths map to one editor directory.</summary>
    public IReadOnlyList<string> PreferredBreakpointSourceRoots { get; init; } = [];
    public TimeSpan CommandTimeout { get; init; } = TimeSpan.FromSeconds(15);
}

public sealed record DebugFrame(int Level, string Address, string Function, string? File, string? FullName,
    string? LocalPath, int? Line, MiValue Raw);
public sealed record DebugVariable(string Name, string? Value, string? Type, string? ObjectName = null,
    int? Children = null, bool IsArgument = false);
public sealed record DebugRegister(int Number, string Name, string Value);
public sealed record DebugInstruction(string Address, string? Function, string? Offset, string Instruction,
    string? Opcodes);
public sealed record DebugBreakpoint(string Number, string? Type, bool Enabled, string? Address,
    string? File, int? Line, string? Condition, MiValue Raw);

public sealed class GdbCommandException(string command, MiRecord response)
    : Exception(response.GetString("msg") ?? $"GDB rejected {command}")
{
    public string Command { get; } = command;
    public MiRecord Response { get; } = response;
}

internal static class EventDispatch
{
    // A UI callback must not terminate a protocol reader or strand pending commands.
    public static void Raise<T>(Action<T>? handlers, T value)
    {
        if (handlers is null) return;
        foreach (Action<T> handler in handlers.GetInvocationList())
        {
            try { handler(value); }
            catch { /* The subscriber owns presentation errors. */ }
        }
    }
}
