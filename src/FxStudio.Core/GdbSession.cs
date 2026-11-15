using System.Collections.Concurrent;
using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace FxStudio.Core;

/// <summary>One GDB/MI2 process. All events are raised on background threads.</summary>
public sealed class GdbSession : IAsyncDisposable
{
    private Process? _process;
    private Task? _stdoutTask;
    private Task? _stderrTask;
    private Task? _exitTask;
    private readonly ConcurrentDictionary<long, TaskCompletionSource<MiRecord>> _pending = new();
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private readonly CancellationTokenSource _lifetime = new();
    private readonly TaskCompletionSource<MiRecord> _initialStop = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private long _nextToken;
    private bool _disposed;
    private readonly object _disposeLock = new();
    private Task? _disposeTask;
    private GdbLaunchOptions? _options;
    private IReadOnlyList<string>? _registerNames;

    public event Action<string>? Output;
    public event Action<MiRecord>? RecordReceived;
    public event Action<MiRecord>? Stopped;
    public event Action<DebugState>? StateChanged;
    public DebugState State { get; private set; } = DebugState.NotStarted;
    public MiRecord? LastStop { get; private set; }
    public bool IsAlive
    {
        get
        {
            if (_disposed || _process is null) return false;
            try { return !_process.HasExited; }
            catch (InvalidOperationException) { return false; } // Process.Start may have failed.
        }
    }

    public Task StartAsync(string gdbPath, string elfPath, int gdbPort,
        IReadOnlyList<SourceMapping>? sourceMappings = null, CancellationToken cancellationToken = default)
    {
        var file = string.IsNullOrEmpty(elfPath) ? null : Path.GetFullPath(elfPath);
        return StartAsync(new GdbLaunchOptions
        {
            ExecutablePath = File.Exists(gdbPath) ? Path.GetFullPath(gdbPath) : gdbPath,
            // Native MinGW GDB cannot reliably open UTF-8 absolute directories.
            // Windows sets the working directory through its Unicode process API.
            ElfPath = file is null ? "" : Path.GetFileName(file),
            WorkingDirectory = file is null ? null : Path.GetDirectoryName(file), Port = gdbPort,
            GdbSourceMappings = sourceMappings ?? [], SourceMappings = sourceMappings ?? []
        }, cancellationToken);
    }

    public async Task StartAsync(GdbLaunchOptions options, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        cancellationToken.ThrowIfCancellationRequested();
        if (_process is not null) throw new InvalidOperationException("Create a new session to start GDB again.");
        if (options.Port is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(options.Port));
        _options = options;
        ChangeState(DebugState.Starting);
        var start = new ProcessStartInfo(options.ExecutablePath)
        {
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true, StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8, StandardInputEncoding = new UTF8Encoding(false)
        };
        if (options.WorkingDirectory is not null) start.WorkingDirectory = options.WorkingDirectory;
        foreach (var argument in options.Arguments) start.ArgumentList.Add(argument);
        // Keep MI deterministic even when a user's machine has a non-English locale.
        start.Environment["LC_ALL"] = "C.UTF-8";
        _process = new Process { StartInfo = start };
        try
        {
            if (!_process.Start()) throw new InvalidOperationException("Could not start GDB.");
            var process = _process;
            _stdoutTask = Task.Run(() => ReadStdoutAsync(process));
            _stderrTask = Task.Run(() => ReadStderrAsync(process));
            _exitTask = Task.Run(() => ObserveExitAsync(process));
            await CommandAsync("-gdb-set pagination off", cancellationToken);
            await CommandAsync("-gdb-set confirm off", cancellationToken);
            await CommandAsync("-gdb-set auto-load off", cancellationToken);
            await CommandAsync("-gdb-set mi-async on", cancellationToken);
            await CommandAsync("-gdb-set print elements 200", cancellationToken);
            await CommandAsync("-gdb-set architecture " + SettingToken(options.Architecture), cancellationToken);
            await CommandAsync("-gdb-set endian " + SettingToken(options.Endian), cancellationToken);
            await CommandAsync(string.IsNullOrEmpty(options.ElfPath) ? "-file-exec-and-symbols" :
                "-file-exec-and-symbols " + MiValue.Quote(options.ElfPath), cancellationToken);
            foreach (var mapping in options.GdbSourceMappings)
            {
                var command = "set substitute-path " + MiValue.Quote(mapping.From) + " " + MiValue.Quote(mapping.To);
                await CommandAsync("-interpreter-exec console " + MiValue.Quote(command), cancellationToken);
            }
            await CommandAsync("-target-select remote 127.0.0.1:" + options.Port, cancellationToken,
                TimeSpan.FromSeconds(25));
            // Do not manufacture a stopped state before the target's actual stop arrives.
            await _initialStop.Task.WaitAsync(TimeSpan.FromSeconds(10), cancellationToken);
        }
        catch
        {
            ChangeState(DebugState.Faulted);
            TerminateProcess();
            throw;
        }
    }

    public async Task<MiRecord> CommandAsync(string command, CancellationToken cancellationToken = default,
        TimeSpan? timeout = null)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (command.Length == 0 || command[0] != '-' || command.Contains('\n') || command.Contains('\r'))
            throw new ArgumentException("Send one MI command, beginning with '-' and containing no raw newlines.", nameof(command));
        var process = _process;
        if (process is null || process.HasExited) throw new InvalidOperationException("GDB is not running.");
        var token = Interlocked.Increment(ref _nextToken);
        var completion = new TaskCompletionSource<MiRecord>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_pending.TryAdd(token, completion)) throw new InvalidOperationException("Duplicate MI token.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _lifetime.Token);
        linked.CancelAfter(timeout ?? _options?.CommandTimeout ?? TimeSpan.FromSeconds(15));
        try
        {
            await _writeLock.WaitAsync(linked.Token);
            try
            {
                await process.StandardInput.WriteLineAsync((token.ToString(CultureInfo.InvariantCulture) + command)
                    .AsMemory(), linked.Token);
                await process.StandardInput.FlushAsync(linked.Token);
            }
            finally { _writeLock.Release(); }
            var response = await completion.Task.WaitAsync(linked.Token);
            if (response.Class == "error") throw new GdbCommandException(command, response);
            return response;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && !_lifetime.IsCancellationRequested)
        {
            throw new TimeoutException($"GDB command timed out: {command}");
        }
        finally { _pending.TryRemove(token, out _); }
    }

    public Task<MiRecord> ContinueAsync(CancellationToken ct = default) => CommandAsync("-exec-continue", ct);
    public Task<MiRecord> PauseAsync(CancellationToken ct = default) => CommandAsync("-exec-interrupt --all", ct);
    public Task<MiRecord> StepAsync(CancellationToken ct = default) => CommandAsync("-exec-step", ct);
    public Task<MiRecord> NextAsync(CancellationToken ct = default) => CommandAsync("-exec-next", ct);
    public Task<MiRecord> FinishAsync(CancellationToken ct = default) => CommandAsync("-exec-finish", ct);
    public Task<MiRecord> StepInstructionAsync(CancellationToken ct = default) => CommandAsync("-exec-step-instruction", ct);
    public Task<MiRecord> NextInstructionAsync(CancellationToken ct = default) => CommandAsync("-exec-next-instruction", ct);
    public Task<MiRecord> SelectFrameAsync(int level, CancellationToken ct = default) =>
        CommandAsync("-stack-select-frame " + Nonnegative(level), ct);

    public async Task<DebugBreakpoint> InsertBreakpointAsync(string location, string? condition = null,
        bool temporary = false, CancellationToken ct = default)
    {
        var command = "-break-insert -f " + (temporary ? "-t " : "") +
            (string.IsNullOrEmpty(condition) ? "" : "-c " + MiValue.Quote(condition) + " ") + MiValue.Quote(location);
        var record = await CommandAsync(command, ct);
        return ParseBreakpoint(record.Results["bkpt"] ?? throw new InvalidDataException("GDB did not return a breakpoint."));
    }

    public async Task<DebugBreakpoint> InsertWatchpointAsync(string expression, string access = "write", CancellationToken ct = default)
    {
        var flag = access switch { "write" => "", "read" => "-r ", "access" => "-a ", _ => throw new ArgumentException("Unknown watchpoint access.", nameof(access)) };
        var result = await CommandAsync("-break-watch " + flag + MiValue.Quote(expression), ct);
        var value = result.Results["wpt"] ?? result.Results["hw-rwpt"] ?? result.Results["hw-awpt"] ??
            throw new InvalidDataException("GDB did not return a watchpoint.");
        return ParseBreakpoint(value);
    }

    public Task<MiRecord> DeleteBreakpointAsync(string number, CancellationToken ct = default) =>
        CommandAsync("-break-delete " + BreakpointNumber(number), ct);
    public Task<MiRecord> SetBreakpointEnabledAsync(string number, bool enabled, CancellationToken ct = default) =>
        CommandAsync((enabled ? "-break-enable " : "-break-disable ") + BreakpointNumber(number), ct);
    public Task<MiRecord> SetBreakpointConditionAsync(string number, string? condition, CancellationToken ct = default) =>
        CommandAsync("-break-condition " + BreakpointNumber(number) +
            (string.IsNullOrEmpty(condition) ? "" : " " + MiValue.Quote(condition)), ct);

    public async Task<IReadOnlyList<DebugBreakpoint>> GetBreakpointsAsync(CancellationToken ct = default)
    {
        var response = await CommandAsync("-break-list", ct);
        return (response.Results["BreakpointTable"]?["body"]?.Items ?? [])
            .Select(x => ParseBreakpoint(x["bkpt"] ?? x)).ToArray();
    }

    public async Task<IReadOnlyList<DebugVariable>> GetLocalsAsync(CancellationToken ct = default)
    {
        var response = await CommandAsync("-stack-list-variables --simple-values", ct);
        return (response.Results["variables"]?.Items ?? []).Select(x => new DebugVariable(
            x.GetString("name") ?? "", x.GetString("value"), x.GetString("type"),
            IsArgument: x.GetString("arg") == "1")).ToArray();
    }

    public async Task<string> EvaluateAsync(string expression, CancellationToken ct = default) =>
        (await CommandAsync("-data-evaluate-expression " + MiValue.Quote(expression), ct)).GetString("value") ?? "";

    public async Task<DebugVariable> CreateVariableObjectAsync(string expression, CancellationToken ct = default)
    {
        var r = await CommandAsync("-var-create - * " + MiValue.Quote(expression), ct);
        return new(expression, r.GetString("value"), r.GetString("type"), r.GetString("name"), r.Results.GetInt("numchild"));
    }

    public async Task<IReadOnlyList<DebugVariable>> GetVariableChildrenAsync(string objectName, CancellationToken ct = default)
    {
        var r = await CommandAsync("-var-list-children --all-values " + MiValue.Quote(objectName), ct);
        return (r.Results["children"]?.Items ?? []).Select(x => x["child"] ?? x).Select(x => new DebugVariable(
            x.GetString("exp") ?? "", x.GetString("value"), x.GetString("type"), x.GetString("name"), x.GetInt("numchild"))).ToArray();
    }

    public Task<MiRecord> DeleteVariableObjectAsync(string objectName, CancellationToken ct = default) =>
        CommandAsync("-var-delete " + MiValue.Quote(objectName), ct);
    public Task<MiRecord> AssignVariableObjectAsync(string objectName, string expression, CancellationToken ct = default) =>
        CommandAsync("-var-assign " + MiValue.Quote(objectName) + " " + MiValue.Quote(expression), ct);

    public async Task<IReadOnlyList<DebugFrame>> GetStackAsync(CancellationToken ct = default)
    {
        var r = await CommandAsync("-stack-list-frames 0 127", ct);
        return (r.Results["stack"]?.Items ?? []).Select(x => ParseFrame(x["frame"] ?? x)).ToArray();
    }

    public DebugFrame? GetStoppedFrame() => LastStop?.Results["frame"] is { } frame ? ParseFrame(frame) : null;

    public async Task<IReadOnlyList<DebugRegister>> GetRegistersAsync(CancellationToken ct = default)
    {
        if (_registerNames is null)
        {
            var names = await CommandAsync("-data-list-register-names", ct);
            _registerNames = (names.Results["register-names"]?.Items ?? []).Select(x => x.Text ?? "").ToArray();
        }
        var r = await CommandAsync("-data-list-register-values x", ct);
        return (r.Results["register-values"]?.Items ?? []).Select(x =>
        {
            var number = x.GetInt("number") ?? -1;
            return new DebugRegister(number, number >= 0 && number < _registerNames.Count ? _registerNames[number] : "?",
                x.GetString("value") ?? "");
        }).Where(x => x.Name.Length > 0).ToArray();
    }

    public Task<MiRecord> WriteRegisterAsync(int number, string value, CancellationToken ct = default) =>
        CommandAsync("-data-write-register-values x " + Nonnegative(number) + " " + MiValue.Quote(value), ct);

    public async Task<byte[]> ReadMemoryAsync(string address, int count, CancellationToken ct = default)
    {
        if (count is < 1 or > 1024 * 1024) throw new ArgumentOutOfRangeException(nameof(count));
        var r = await CommandAsync("-data-read-memory-bytes " + MiValue.Quote(address) + " " + count, ct);
        var blocks = r.Results["memory"]?.Items ?? [];
        var bytes = blocks.SelectMany(x => Convert.FromHexString(x.GetString("contents") ?? "")).ToArray();
        if (bytes.Length != count) throw new InvalidDataException($"GDB returned {bytes.Length} of {count} requested memory bytes.");
        return bytes;
    }

    public Task<MiRecord> WriteMemoryAsync(string address, ReadOnlyMemory<byte> data, CancellationToken ct = default)
    {
        if (data.Length is < 1 or > 1024 * 1024) throw new ArgumentOutOfRangeException(nameof(data));
        return CommandAsync("-data-write-memory-bytes " + MiValue.Quote(address) + " " + Convert.ToHexString(data.Span), ct);
    }

    public async Task<IReadOnlyList<DebugInstruction>> GetDisassemblyAsync(string start, string end, CancellationToken ct = default)
    {
        var r = await CommandAsync("-data-disassemble -s " + MiValue.Quote(start) + " -e " + MiValue.Quote(end) + " -- 2", ct);
        return (r.Results["asm_insns"]?.Items ?? []).Select(x => new DebugInstruction(x.GetString("address") ?? "",
            x.GetString("func-name"), x.GetString("offset"), x.GetString("inst") ?? "", x.GetString("opcodes"))).ToArray();
    }

    public string MapSourcePath(string path)
    {
        var normalized = path.Replace('\\', '/');
        foreach (var mapping in (_options?.SourceMappings ?? []).OrderByDescending(x => x.From.Length))
        {
            var from = mapping.From.Replace('\\', '/').TrimEnd('/');
            var comparison = from.Contains(':') ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            if (normalized.Equals(from, comparison) || normalized.StartsWith(from + "/", comparison))
                return mapping.To.TrimEnd('/', '\\') + normalized[from.Length..];
        }
        return path;
    }

    public string GetBreakpointLocation(string localPath, int line)
    {
        if (line < 1) throw new ArgumentOutOfRangeException(nameof(line));
        var normalized = localPath.Replace('\\', '/');
        // Prefer the path actually emitted into DWARF over another alias of the source root.
        var compiledRoots = (_options?.GdbSourceMappings ?? []).Select(x => x.From)
            .Concat(_options?.PreferredBreakpointSourceRoots ?? []).ToHashSet(StringComparer.Ordinal);
        var mappings = (_options?.SourceMappings ?? []).OrderByDescending(x => x.To.Length)
            .ThenByDescending(x => compiledRoots.Contains(x.From));
        foreach (var mapping in mappings)
        {
            var to = mapping.To.Replace('\\', '/').TrimEnd('/');
            var comparison = to.Contains(':') ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            if (normalized.Equals(to, comparison) || normalized.StartsWith(to + "/", comparison))
                return mapping.From.TrimEnd('/') + normalized[to.Length..] + ":" + line;
        }
        return normalized + ":" + line;
    }

    private DebugFrame ParseFrame(MiValue x)
    {
        var path = x.GetString("fullname") ?? x.GetString("file");
        return new(x.GetInt("level") ?? 0, x.GetString("addr") ?? "", x.GetString("func") ?? "??",
            x.GetString("file"), x.GetString("fullname"), path is null ? null : MapSourcePath(path), x.GetInt("line"), x);
    }

    private static DebugBreakpoint ParseBreakpoint(MiValue x) => new(x.GetString("number") ?? "", x.GetString("type"),
        x.GetString("enabled") != "n", x.GetString("addr"), x.GetString("fullname") ?? x.GetString("file"),
        x.GetInt("line"), x.GetString("cond"), x);
    private static string Nonnegative(int value) => value >= 0 ? value.ToString(CultureInfo.InvariantCulture) :
        throw new ArgumentOutOfRangeException(nameof(value));
    private static string SettingToken(string value) => value.Length > 0 && value.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_')
        ? value : throw new ArgumentException("Invalid GDB setting token.", nameof(value));
    private static string BreakpointNumber(string value) => value.Length > 0 && value.All(c => char.IsAsciiDigit(c) || c == '.')
        ? value : throw new ArgumentException("Invalid breakpoint number.", nameof(value));

    private async Task ReadStdoutAsync(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync(_lifetime.Token) is { } line)
            {
                MiRecord? record;
                try { record = MiParser.Parse(line); }
                catch (MiParseException ex)
                {
                    EventDispatch.Raise(Output, "GDB protocol error: " + ex.Message + "\n" + line);
                    FailPending(ex);
                    ChangeState(DebugState.Faulted);
                    TerminateProcess();
                    return;
                }
                if (record is null) continue;
                EventDispatch.Raise(RecordReceived, record);
                if (record.IsStream) EventDispatch.Raise(Output, record.StreamText ?? "");
                if (record.Kind == '*' && record.Class == "running") ChangeState(DebugState.Running);
                if (record.Kind == '*' && record.Class == "stopped")
                {
                    LastStop = record;
                    var reason = record.GetString("reason");
                    ChangeState(reason is "exited-normally" or "exited" or "exited-signalled" ? DebugState.Exited : DebugState.Stopped);
                    EventDispatch.Raise(Stopped, record);
                    _initialStop.TrySetResult(record);
                }
                if (record.IsResult && record.Class == "running") ChangeState(DebugState.Running);
                if (record.IsResult && record.Token is { } token && _pending.TryRemove(token, out var completion))
                    completion.TrySetResult(record);
            }
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested) { }
        catch (Exception ex) { FailPending(ex); if (!_disposed) ChangeState(DebugState.Faulted); }
    }

    private async Task ReadStderrAsync(Process process)
    {
        try
        {
            while (await process.StandardError.ReadLineAsync(_lifetime.Token) is { } line)
                EventDispatch.Raise(Output, line + Environment.NewLine);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested) { }
        catch (IOException) { }
    }

    private async Task ObserveExitAsync(Process process)
    {
        try
        {
            await process.WaitForExitAsync();
            if (_stdoutTask is not null) await _stdoutTask;
            if (_stderrTask is not null) await _stderrTask;
            FailPending(new EndOfStreamException($"GDB exited with code {process.ExitCode}."));
            if (!_disposed && State != DebugState.Faulted) ChangeState(DebugState.Exited);
        }
        catch (Exception ex) { FailPending(ex); }
    }

    private void ChangeState(DebugState state)
    {
        if (State == state) return;
        State = state;
        EventDispatch.Raise(StateChanged, state);
    }

    private void FailPending(Exception exception)
    {
        _initialStop.TrySetException(exception);
        foreach (var (token, completion) in _pending)
            if (_pending.TryRemove(token, out _)) completion.TrySetException(exception);
    }

    private void TerminateProcess()
    {
        try { if (_process is { HasExited: false }) _process.Kill(entireProcessTree: true); }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
    }

    public ValueTask DisposeAsync()
    {
        lock (_disposeLock)
        {
            if (_disposed && _disposeTask is null) return ValueTask.CompletedTask;
            return new ValueTask(_disposeTask ??= DisposeCoreAsync());
        }
    }

    private async Task DisposeCoreAsync()
    {
        if (_disposed) return;
        if (IsAlive)
        {
            try
            {
                if (State == DebugState.Running)
                {
                    var stopped = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    void OnStop(MiRecord _) => stopped.TrySetResult(true);
                    Stopped += OnStop;
                    try
                    {
                        if (State == DebugState.Running)
                        {
                            await CommandAsync("-exec-interrupt --all", timeout: TimeSpan.FromSeconds(2));
                            await stopped.Task.WaitAsync(TimeSpan.FromSeconds(2));
                        }
                    }
                    finally { Stopped -= OnStop; }
                }
                await CommandAsync("-gdb-exit", timeout: TimeSpan.FromSeconds(2));
            }
            catch { /* An unresponsive remote target must not keep the IDE alive. */ }
        }
        _disposed = true;
        TerminateProcess();
        await _lifetime.CancelAsync();
        FailPending(new ObjectDisposedException(nameof(GdbSession)));
        if (_exitTask is not null)
            try { await _exitTask.WaitAsync(TimeSpan.FromSeconds(3)); } catch { }
        _process?.Dispose();
        ChangeState(DebugState.Disposed);
    }
}
