using System.Diagnostics;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace FxStudio.Core;

/// <summary>SuperH emulator process and its loopback control channel. Execution belongs to GDB.</summary>
public sealed class EmulatorSession : IAsyncDisposable
{
    private Process? _process;
    private Task? _stdoutTask;
    private Task? _stderrTask;
    private Task? _exitTask;
    private TcpClient? _control;
    private StreamReader? _reader;
    private StreamWriter? _writer;
    private readonly SemaphoreSlim _controlLock = new(1, 1);
    private readonly TaskCompletionSource<bool> _ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly CancellationTokenSource _lifetime = new();
    private bool _disposed;
    private readonly object _disposeLock = new();
    private Task? _disposeTask;
    public event Action<string>? Output;
    public event Action<int>? Exited;
    public int GdbPort { get; private set; }
    public int ControlPort { get; private set; }
    public string FramebufferPath { get; private set; } = "";
    public bool IsAlive
    {
        get
        {
            if (_disposed || _process is null) return false;
            try { return !_process.HasExited; }
            catch (InvalidOperationException) { return false; }
        }
    }

    public async Task StartAsync(string executable, string g1aPath, string framebufferPath,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        cancellationToken.ThrowIfCancellationRequested();
        if (_process is not null) throw new InvalidOperationException("Create a new session to restart the emulator.");
        if (!File.Exists(g1aPath)) throw new FileNotFoundException("G1A was not found.", g1aPath);
        FramebufferPath = Path.GetFullPath(framebufferPath);
        Directory.CreateDirectory(Path.GetDirectoryName(FramebufferPath)!);
        var start = new ProcessStartInfo(File.Exists(executable) ? Path.GetFullPath(executable) : executable)
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
            RedirectStandardError = true, WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(g1aPath))!,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var arg in new[] { "--gdb-port", "0", "--control-port", "0", "--framebuffer", FramebufferPath, Path.GetFullPath(g1aPath) })
            start.ArgumentList.Add(arg);
        _process = new Process { StartInfo = start };
        try
        {
            if (!_process.Start()) throw new InvalidOperationException("Could not start the emulator.");
            var process = _process;
            _stdoutTask = Task.Run(() => ReadStdoutAsync(process));
            _stderrTask = Task.Run(() => ReadStderrAsync(process));
            _exitTask = Task.Run(() => ObserveExitAsync(process));
            await _ready.Task.WaitAsync(TimeSpan.FromSeconds(20), cancellationToken);
            await EnsureControlConnectedAsync(cancellationToken);
        }
        catch { TerminateProcess(); throw; }
    }

    public Task<JsonElement> SendKeyAsync(string key, bool down, CancellationToken cancellationToken = default) =>
        SendControlAsync(new { command = "key", key, down }, cancellationToken);
    public Task<JsonElement> StatusAsync(CancellationToken cancellationToken = default) =>
        SendControlAsync(new { command = "status" }, cancellationToken);

    public async Task<JsonElement> SendControlAsync<T>(T request, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!IsAlive) throw new InvalidOperationException("The emulator is not running.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _lifetime.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(5));
        await _controlLock.WaitAsync(linked.Token);
        try
        {
            await EnsureControlConnectedAsync(linked.Token);
            await _writer!.WriteLineAsync(JsonSerializer.Serialize(request).AsMemory(), linked.Token);
            await _writer.FlushAsync(linked.Token);
            var line = await _reader!.ReadLineAsync(linked.Token) ?? throw new EndOfStreamException("Emulator closed its control connection.");
            using var doc = JsonDocument.Parse(line);
            var value = doc.RootElement.Clone();
            if (value.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False)
                throw new InvalidOperationException(value.TryGetProperty("error", out var error) ? error.ToString() : "Emulator rejected the command.");
            return value;
        }
        catch
        {
            // A timed-out reply must never be mistaken for the next key's acknowledgement.
            CloseControl();
            throw;
        }
        finally { _controlLock.Release(); }
    }

    private async Task EnsureControlConnectedAsync(CancellationToken ct)
    {
        if (_control is { Connected: true }) return;
        CloseControl();
        var client = new TcpClient();
        try { await client.ConnectAsync("127.0.0.1", ControlPort, ct); }
        catch { client.Dispose(); throw; }
        client.NoDelay = true;
        _control = client;
        _reader = new StreamReader(client.GetStream(), Encoding.UTF8, false, 4096, leaveOpen: true);
        _writer = new StreamWriter(client.GetStream(), new UTF8Encoding(false), 4096, leaveOpen: true) { NewLine = "\n" };
    }

    private async Task ReadStdoutAsync(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync(_lifetime.Token) is { } line)
            {
                EventDispatch.Raise(Output, line);
                if (!line.StartsWith('{')) continue;
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var root = doc.RootElement;
                    if (root.TryGetProperty("event", out var evt) && evt.GetString() == "ready")
                    {
                        var gdb = root.GetProperty("gdbPort").GetInt32();
                        var control = root.GetProperty("controlPort").GetInt32();
                        if (gdb is < 1 or > 65535 || control is < 1 or > 65535)
                            throw new InvalidDataException("The emulator returned invalid ports.");
                        GdbPort = gdb; ControlPort = control;
                        _ready.TrySetResult(true);
                    }
                }
                catch (Exception ex) when (ex is JsonException or KeyNotFoundException or InvalidOperationException or InvalidDataException)
                {
                    _ready.TrySetException(new InvalidDataException("Invalid emulator ready response.", ex));
                }
            }
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested) { }
        catch (Exception ex) { _ready.TrySetException(ex); }
    }

    private async Task ReadStderrAsync(Process process)
    {
        try
        {
            while (await process.StandardError.ReadLineAsync(_lifetime.Token) is { } line) EventDispatch.Raise(Output, line);
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
            _ready.TrySetException(new EndOfStreamException($"Emulator exited with code {process.ExitCode} before becoming ready."));
            EventDispatch.Raise(Exited, process.ExitCode);
        }
        catch (Exception ex) { _ready.TrySetException(ex); }
    }

    private void CloseControl()
    {
        // Disposing a writer can flush into an already closed socket; still release all resources.
        try { _reader?.Dispose(); } catch (IOException) { }
        try { _writer?.Dispose(); } catch (IOException) { }
        _control?.Dispose();
        _reader = null; _writer = null; _control = null;
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
        if (IsAlive && ControlPort > 0)
        {
            try
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
                await SendControlAsync(new { command = "quit" }, timeout.Token);
            }
            catch { }
        }
        _disposed = true;
        TerminateProcess();
        await _lifetime.CancelAsync();
        CloseControl();
        if (_exitTask is not null) try { await _exitTask.WaitAsync(TimeSpan.FromSeconds(3)); } catch { }
        _process?.Dispose();
    }
}
