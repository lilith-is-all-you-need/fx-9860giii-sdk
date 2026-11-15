using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using FxStudio.Automation;

namespace FxStudio.Agent;

internal static class Wire
{
    internal static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    internal static JsonElement Element(object? value) => JsonSerializer.SerializeToElement(value, Json);
    internal static string Text(JsonElement value, string key, string? fallback = null) => !value.TryGetProperty(key, out var v) ? fallback ?? throw new ArgumentException("Expected string: " + key) : v.ValueKind == JsonValueKind.String ? v.GetString()! : throw new ArgumentException("Expected string: " + key);
    internal static int Number(JsonElement value, string key, int fallback = 0) => !value.TryGetProperty(key, out var v) ? fallback : v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n) ? n : throw new ArgumentException("Expected integer: " + key);
    internal static void Fields(JsonElement value, params string[] fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new ArgumentException("Expected an argument object.");
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var p in value.EnumerateObject()) {
            if (!names.Add(p.Name)) throw new ArgumentException("Duplicate field: " + p.Name);
            if (!fields.Contains(p.Name)) throw new ArgumentException("Unknown field: " + p.Name);
        }
    }
}

internal sealed class AgentHost : IAsyncDisposable
{
    private readonly AutomationService _service;
    private readonly object _gate = new();
    private readonly Dictionary<string, Operation> _operations = [];
    private readonly Dictionary<string, (string Fingerprint, Operation Operation)> _requests = [];
    private readonly Queue<EventRecord> _events = [];
    private readonly CancellationTokenSource _lifetime = new();
    private long _eventSequence;
    private bool _disposing;
    private const int MaximumOperations = 1024, ReservedCloseOperations = 8, MaximumEvents = 2048;
    internal AgentHost(string package, string? data) { _service = new(package, data); _service.Event += e => AddEvent(e.SessionId, e.Kind, e.Data); }

    internal object Discover(string? command)
    {
        var commands = _service.Commands.Where(c => command is null || c.Name == command).ToArray();
        if (command is not null && commands.Length == 0) throw new AutomationException("UNKNOWN_COMMAND", "Command not found: " + command);
        return new { contractVersion = "1.0", productVersion = "0.2.0", commands,
            target = new { family = "fx-9860GIII", emulatorProfile = "FX9750G3 / SH7305", reportedOsVersion = "03.60.0200", physicalDeviceDebugger = false, fullCasioOs = false, inferiorFunctionCalls = false },
            sdk = new { nativeWindows = true, fxsdkVersion = "2.11.0", gintVersion = "2.11.0", gccVersion = "14.1.0", fullFxsdkCli = false, fxlink = false, cppExceptions = false, cppThreads = false,
                resources = new { fxconvImages = true, fxconvBitmapFonts = true, fxconvBinary = true, automaticCompression = false, importWizard = false, convertedResourcePreview = false } },
            limits = new { maximumSessions = 8, maximumOperations = MaximumOperations, reservedCloseOperations = ReservedCloseOperations, retainedEvents = MaximumEvents, maximumRequestBytes = 1_048_576, maximumWaitMs = 1000 },
            guarantees = new[] { "Commands are independently versioned; additive catalog changes preserve tool envelopes.", "requestKey identifies an exact command submission for this host lifetime; reuse with different input is rejected.", "Cancellation is cooperative and does not roll back completed target writes or key input.", "A running snapshot is explicitly inconsistent; a stopped snapshot is guarded by the session command lock.", "Events have a cursor and explicit gap detection. Operations remain queryable until this process exits.", "Only native Windows automation sessions are supported; the desktop IDE owns separate sessions." },
            workflow = new[] { "session.open", "build.run", "debug.launch", "debug.snapshot", "debug.resume", "debug.key", "debug.pause", "debug.snapshot", "session.close" } };
    }

    internal async Task<object> ExecuteAsync(JsonElement input, CancellationToken ct)
    {
        Wire.Fields(input, "command", "version", "arguments", "requestKey", "waitMs");
        var command = Wire.Text(input, "command");
        var version = Wire.Number(input, "version", 1);
        var versions = _service.Commands.Where(c => c.Name == command).ToArray();
        if (versions.Length == 0) throw new AutomationException("UNKNOWN_COMMAND", "Command not found: " + command);
        if (!versions.Any(c => c.Version == version)) throw new AutomationException("UNSUPPORTED_VERSION", $"{command} supports versions {string.Join(", ", versions.Select(c => c.Version))}.");
        var arguments = input.TryGetProperty("arguments", out var a) ? a.Clone() : Wire.Element(new { });
        if (arguments.ValueKind != JsonValueKind.Object) throw new ArgumentException("arguments must be an object.");
        var key = Wire.Text(input, "requestKey");
        if (string.IsNullOrWhiteSpace(key) || key.Length > 128) throw new ArgumentException("requestKey must contain 1–128 nonblank characters.");
        var wait = WaitMilliseconds(input);
        var fingerprint = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(command + ":" + version + ":" + Canonical(arguments))));
        Operation operation;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposing, this);
            if (_requests.TryGetValue(key, out var prior))
            {
                if (prior.Fingerprint != fingerprint) throw new AutomationException("REQUEST_KEY_CONFLICT", "requestKey was already used with different input. Use the old key only to retry the same submission.");
                operation = prior.Operation;
            }
            else
            {
                if (_operations.Count >= MaximumOperations && (command != "session.close" || _operations.Count >= MaximumOperations + ReservedCloseOperations)) throw new AutomationException("OPERATION_LIMIT", "This host retains 1024 operations plus 8 reserved close operations. Close sessions (or close stdin) and start a new host.");
                operation = new(command, version, key, arguments, _lifetime.Token);
                _requests.Add(key, (fingerprint, operation));
                _operations.Add(operation.Id, operation);
                operation.Task = Task.Run(() => RunAsync(operation));
            }
        }
        await WaitAsync(operation, wait, ct);
        return View(operation);
    }

    private static string Canonical(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Object => "{" + string.Join(",", value.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal).Select(p => JsonSerializer.Serialize(p.Name) + ":" + Canonical(p.Value))) + "}",
        JsonValueKind.Array => "[" + string.Join(",", value.EnumerateArray().Select(Canonical)) + "]",
        JsonValueKind.String => JsonSerializer.Serialize(value.GetString()),
        _ => value.GetRawText()
    };

    private async Task RunAsync(Operation operation)
    {
        lock (_gate) { operation.Status = "running"; operation.StartedAt = DateTimeOffset.UtcNow; }
        AddEvent(operation.SessionId, "operation.started", new { operationId = operation.Id, operation.Command, operation.Version });
        try
        {
            operation.Cancellation.Token.ThrowIfCancellationRequested();
            var result = await _service.ExecuteAsync(operation.Command, operation.Version, operation.Arguments, operation.Cancellation.Token);
            var json = Wire.Element(result);
            lock (_gate) { operation.Result = json; operation.Status = "succeeded"; }
        }
        catch (Exception ex)
        {
            var cancelled = ex is OperationCanceledException && operation.Cancellation.IsCancellationRequested;
            var error = ex is AutomationException domain ? new ErrorInfo(domain.Code, domain.Message, domain.Retryable)
                : new ErrorInfo(cancelled ? "CANCELLED" : ex is ArgumentException or JsonException ? "INVALID_ARGUMENT" : "INTERNAL_ERROR", ex.Message, false);
            lock (_gate) { operation.Status = cancelled ? "cancelled" : "failed"; operation.Error = error; }
        }
        finally
        {
            lock (_gate) operation.CompletedAt = DateTimeOffset.UtcNow;
            AddEvent(operation.SessionId, "operation.completed", new { operationId = operation.Id, status = operation.Status, error = operation.Error });
        }
    }

    internal async Task<object> OperationAsync(JsonElement input, CancellationToken ct)
    {
        Wire.Fields(input, "operationId", "action", "waitMs");
        var id = Wire.Text(input, "operationId");
        var action = Wire.Text(input, "action", "get");
        if (action is not ("get" or "cancel")) throw new ArgumentException("action must be get or cancel.");
        var wait = WaitMilliseconds(input);
        Operation operation;
        lock (_gate) operation = _operations.GetValueOrDefault(id) ?? throw new AutomationException("OPERATION_NOT_FOUND", "Unknown operationId.");
        if (action == "cancel") { lock (_gate) operation.CancelRequested = true; await operation.Cancellation.CancelAsync(); }
        await WaitAsync(operation, wait, ct);
        return View(operation);
    }

    private object View(Operation operation)
    {
        lock (_gate) return new { contractVersion = "1.0", operation = new { operationId = operation.Id, operation.RequestKey, operation.Command, operation.Version,
            operation.SessionId, operation.Status, operation.CancelRequested, operation.CreatedAt, operation.StartedAt, operation.CompletedAt,
            result = operation.Result, error = operation.Error } };
    }

    private static int WaitMilliseconds(JsonElement input)
    {
        var wait = Wire.Number(input, "waitMs");
        if (wait is < 0 or > 1000) throw new ArgumentException("waitMs must be 0–1000.");
        return wait;
    }
    private static async Task WaitAsync(Operation operation, int milliseconds, CancellationToken ct)
    {
        if (milliseconds == 0) return;
        try { await operation.Task.WaitAsync(TimeSpan.FromMilliseconds(milliseconds), ct); } catch (TimeoutException) { }
    }

    private void AddEvent(string? sessionId, string kind, object? data)
    {
        var json = Wire.Element(data);
        if (json.GetRawText().Length > 16384) json = Wire.Element(new { truncated = true, text = json.GetRawText()[..16384] });
        lock (_gate)
        {
            _events.Enqueue(new(++_eventSequence, DateTimeOffset.UtcNow, sessionId, kind, json));
            while (_events.Count > MaximumEvents) _events.Dequeue();
        }
    }

    internal object Events(JsonElement input)
    {
        Wire.Fields(input, "after", "limit", "sessionId");
        var after = input.TryGetProperty("after", out var a) && a.ValueKind == JsonValueKind.Number && a.TryGetInt64(out var cursor) ? cursor : input.TryGetProperty("after", out _) ? throw new ArgumentException("after must be an integer.") : 0;
        var limit = Wire.Number(input, "limit", 100);
        var sessionId = input.TryGetProperty("sessionId", out _) ? Wire.Text(input, "sessionId") : null;
        if (after < 0 || limit is < 1 or > 200) throw new ArgumentException("after must be nonnegative; limit must be 1–200.");
        lock (_gate)
        {
            if (after > _eventSequence) throw new ArgumentException("Event cursor is ahead of this host. Cursors do not survive host restart.");
            var oldest = _events.TryPeek(out var first) ? first.Sequence : _eventSequence + 1;
            var eligible = _events.Where(e => e.Sequence > after && (sessionId is null || e.SessionId == sessionId)).ToArray();
            var events = eligible.Take(limit).ToArray();
            var more = eligible.Length > events.Length;
            return new { contractVersion = "1.0", events, nextCursor = more ? events[^1].Sequence : _eventSequence, latestCursor = _eventSequence,
                oldestCursor = oldest, gap = after < oldest - 1, hasMore = more };
        }
    }

    public async ValueTask DisposeAsync()
    {
        Task[] pending;
        lock (_gate) { if (_disposing) return; _disposing = true; pending = _operations.Values.Select(o => o.Task).ToArray(); }
        await _lifetime.CancelAsync();
        await Task.WhenAll(pending);
        await _service.DisposeAsync();
        foreach (var operation in _operations.Values) operation.Cancellation.Dispose();
        _lifetime.Dispose();
    }

    private sealed record ErrorInfo(string Code, string Message, bool Retryable);
    private sealed record EventRecord(long Sequence, DateTimeOffset Timestamp, string? SessionId, string Kind, JsonElement Data);
    private sealed class Operation(string command, int version, string requestKey, JsonElement arguments, CancellationToken lifetime)
    {
        public string Id { get; } = Guid.NewGuid().ToString("N");
        public string Command { get; } = command;
        public int Version { get; } = version;
        public string RequestKey { get; } = requestKey;
        public JsonElement Arguments { get; } = arguments;
        public string? SessionId { get; } = arguments.TryGetProperty("sessionId", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
        public string Status { get; set; } = "queued";
        public DateTimeOffset CreatedAt { get; } = DateTimeOffset.UtcNow;
        public DateTimeOffset? StartedAt { get; set; }
        public DateTimeOffset? CompletedAt { get; set; }
        public bool CancelRequested { get; set; }
        public JsonElement? Result { get; set; }
        public ErrorInfo? Error { get; set; }
        public Task Task { get; set; } = Task.CompletedTask;
        public CancellationTokenSource Cancellation { get; } = CancellationTokenSource.CreateLinkedTokenSource(lifetime);
    }
}
