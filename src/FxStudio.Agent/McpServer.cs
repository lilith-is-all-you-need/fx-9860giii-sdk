using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using FxStudio.Automation;

namespace FxStudio.Agent;

internal sealed class McpServer(AgentHost host)
{
    private readonly SemaphoreSlim _outputLock = new(1, 1);
    private readonly ConcurrentDictionary<string, CancellationTokenSource> _requests = new();
    private int _initialized;
    private bool _ready;
    private CancellationToken _transportCancellation;
    private const string ProtocolVersion = "2025-11-25";

    internal async Task RunAsync(TextReader input, TextWriter output, CancellationToken shutdown)
    {
        var running = new List<Task>();
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(shutdown);
        _transportCancellation = lifetime.Token;
        try
        {
            var lines = new BoundedLines(input);
            while (await lines.ReadAsync(lifetime.Token) is { } line)
            {
                if (Encoding.UTF8.GetByteCount(line) > 1_048_576) { await SendAsync(output, Error(null, -32600, "Request exceeds 1 MiB.")); continue; }
                JsonElement request;
                try { using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 64 }); request = document.RootElement.Clone(); }
                catch (JsonException) { await SendAsync(output, Error(null, -32700, "Invalid JSON.")); continue; }
                if (request.ValueKind != JsonValueKind.Object) { await SendAsync(output, Error(null, -32600, "Expected one JSON-RPC request; batches are not supported.")); continue; }
                if (!request.TryGetProperty("jsonrpc", out var rpc) || rpc.ValueKind != JsonValueKind.String || rpc.GetString() != "2.0" ||
                    !request.TryGetProperty("method", out var method) || method.ValueKind != JsonValueKind.String)
                { await SendAsync(output, Error(null, -32600, "Expected jsonrpc 2.0 and method.")); continue; }
                var name = method.GetString()!;
                var parameters = request.TryGetProperty("params", out var p) ? p : Wire.Element(new { });
                if (!request.TryGetProperty("id", out var id))
                {
                    if (name == "notifications/initialized" && Volatile.Read(ref _initialized) == 1) _ready = true;
                    if (name == "notifications/cancelled" && parameters.ValueKind == JsonValueKind.Object && parameters.TryGetProperty("requestId", out var cancelled) && _requests.TryGetValue(cancelled.GetRawText(), out var cancellation)) {
                        try { await cancellation.CancelAsync(); } catch (ObjectDisposedException) { /* A completed request no longer needs cancelling. */ }
                    }
                    continue;
                }
                if (id.ValueKind is not (JsonValueKind.String or JsonValueKind.Number)) { await SendAsync(output, Error(null, -32600, "Request id must be a string or number.")); continue; }
                var idKey = id.GetRawText();
                var requestCancellation = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                if (!_requests.TryAdd(idKey, requestCancellation)) { requestCancellation.Dispose(); await SendAsync(output, Error(id, -32600, "Duplicate active request id.")); continue; }
                if (_requests.Count > 32) { _requests.TryRemove(idKey, out _); requestCancellation.Dispose(); await SendAsync(output, Error(id, -32000, "Too many concurrent requests.")); continue; }
                // Initialization is completed before the next line is consumed. Other tool calls are bounded waits.
                if (name == "initialize") await HandleAsync(name, parameters, id, idKey, requestCancellation, output);
                else running.Add(HandleAsync(name, parameters, id, idKey, requestCancellation, output));
                running.RemoveAll(t => t.IsCompletedSuccessfully);
            }
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        finally
        {
            await lifetime.CancelAsync();
            try { await Task.WhenAll(running); } catch (IOException) { } catch (OperationCanceledException) { }
        }
    }

    private async Task HandleAsync(string method, JsonElement parameters, JsonElement id, string key, CancellationTokenSource cancellation, TextWriter output)
    {
        try
        {
            object result;
            if (method == "initialize")
            {
                if (Volatile.Read(ref _initialized) != 0) throw new RpcException(-32600, "Already initialized.");
                if (parameters.ValueKind != JsonValueKind.Object) throw new ArgumentException("initialize params must be an object.");
                var requested = Wire.Text(parameters, "protocolVersion");
                if (!parameters.TryGetProperty("capabilities", out var capabilities) || capabilities.ValueKind != JsonValueKind.Object || !parameters.TryGetProperty("clientInfo", out var client) || client.ValueKind != JsonValueKind.Object) throw new ArgumentException("initialize requires capabilities and clientInfo.");
                _ = Wire.Text(client, "name"); _ = Wire.Text(client, "version");
                var version = requested is "2025-11-25" or "2025-06-18" ? requested : ProtocolVersion;
                result = new { protocolVersion = version, capabilities = new { tools = new { listChanged = false } }, serverInfo = new { name = "FxStudio", version = "0.2.0" },
                    instructions = "Use fxstudio_discover to discover versioned commands, then fxstudio_execute with a unique requestKey. Poll fxstudio_operation until terminal. Reuse the same key only for the same submission. Read events for logs. session.open -> build.run -> debug.launch -> debug.snapshot. This server owns separate native simulator sessions; no physical calculator or existing GUI session is controlled. Close sessions when finished." };
                Volatile.Write(ref _initialized, 1);
            }
            else if (method == "ping") result = new { };
            else
            {
                if (!_ready) throw new RpcException(-32002, "Send initialize and notifications/initialized first.");
                result = method switch
                {
                    "tools/list" => ListTools(parameters),
                    "tools/call" => await CallToolAsync(parameters, cancellation.Token),
                    _ => throw new RpcException(-32601, "Method not found: " + method)
                };
            }
            await SendAsync(output, new { jsonrpc = "2.0", id, result });
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { await SendAsync(output, Error(id, -32800, "Request cancelled. A submitted operation continues until fxstudio_operation action=cancel or host shutdown.")); }
        catch (RpcException ex) { await SendAsync(output, Error(id, ex.Code, ex.Message)); }
        catch (Exception ex) when (ex is ArgumentException or JsonException or InvalidOperationException or KeyNotFoundException) { await SendAsync(output, Error(id, -32602, ex.Message)); }
        catch (Exception ex) { await SendAsync(output, Error(id, -32603, ex.Message)); }
        finally { _requests.TryRemove(key, out _); cancellation.Dispose(); }
    }

    private object ListTools(JsonElement parameters)
    {
        Wire.Fields(parameters, "cursor");
        if (parameters.TryGetProperty("cursor", out _)) throw new ArgumentException("This catalog has no continuation cursor.");
        static object Schema(object properties, string[] required) => new { type = "object", properties, required, additionalProperties = false };
        var text = new { type = "string" };
        var wait = new { type = "integer", minimum = 0, maximum = 1000, @default = 0 };
        return new { tools = new object[] {
            new { name = "fxstudio_discover", description = "Discover the stable automation contract and versioned domain commands, including input schemas, side effects and limits. Supply command to inspect one command.", inputSchema = Schema(new { command = text }, []), annotations = new { readOnlyHint = true, openWorldHint = false } },
            new { name = "fxstudio_execute", description = "Submit one discovered command. Returns an operation, not necessarily a completed result. A requestKey provides retry deduplication for this host lifetime. Use operation polling and cancellation. Project builds execute trusted project code.", inputSchema = Schema(new { command = text, version = new { type = "integer", minimum = 1, @default = 1 }, arguments = new { type = "object" }, requestKey = new { type = "string", minLength = 1, maxLength = 128 }, waitMs = wait }, ["command", "arguments", "requestKey"]), annotations = new { readOnlyHint = false, destructiveHint = true, openWorldHint = true } },
            new { name = "fxstudio_operation", description = "Inspect or cancel an operation. Cancellation is cooperative; completed changes are not rolled back. Poll until succeeded, failed or cancelled. Screen snapshots include an image block.", inputSchema = Schema(new { operationId = text, action = new { type = "string", @enum = new[] { "get", "cancel" }, @default = "get" }, waitMs = wait }, ["operationId"]), annotations = new { readOnlyHint = false, destructiveHint = false, openWorldHint = false } },
            new { name = "fxstudio_events", description = "Read build/debug events after a cursor. gap=true means old events expired; get a fresh snapshot. A returned nextCursor is valid only for this host lifetime and selected filter.", inputSchema = Schema(new { after = new { type = "integer", minimum = 0, @default = 0 }, limit = new { type = "integer", minimum = 1, maximum = 200, @default = 100 }, sessionId = text }, []), annotations = new { readOnlyHint = true, openWorldHint = false } }
        } };
    }

    private async Task<object> CallToolAsync(JsonElement parameters, CancellationToken ct)
    {
        if (parameters.ValueKind != JsonValueKind.Object) throw new ArgumentException("Tool parameters must be an object.");
        var name = Wire.Text(parameters, "name");
        var arguments = parameters.TryGetProperty("arguments", out var a) ? a : Wire.Element(new { });
        if (arguments.ValueKind != JsonValueKind.Object) throw new ArgumentException("Tool arguments must be an object.");
        if (name is not ("fxstudio_discover" or "fxstudio_execute" or "fxstudio_operation" or "fxstudio_events")) throw new RpcException(-32602, "Unknown tool: " + name);
        try
        {
            object result;
            switch (name)
            {
                case "fxstudio_discover": Wire.Fields(arguments, "command"); result = host.Discover(arguments.TryGetProperty("command", out _) ? Wire.Text(arguments, "command") : null); break;
                case "fxstudio_execute": result = await host.ExecuteAsync(arguments, ct); break;
                case "fxstudio_operation": result = await host.OperationAsync(arguments, ct); break;
                default: result = host.Events(arguments); break;
            }
            return ToolResult(result);
        }
        catch (AutomationException ex) { return ToolResult(new { contractVersion = "1.0", error = new { code = ex.Code, message = ex.Message, retryable = ex.Retryable } }, true); }
        catch (Exception ex) when (ex is ArgumentException or JsonException) { return ToolResult(new { contractVersion = "1.0", error = new { code = "INVALID_ARGUMENT", message = ex.Message, retryable = false } }, true); }
    }

    private static object ToolResult(object result, bool error = false)
    {
        var node = JsonSerializer.SerializeToNode(result, Wire.Json)!;
        var images = new List<object>();
        void Extract(JsonNode? current)
        {
            if (current is JsonObject obj)
            {
                if (obj.Remove("base64Bmp", out var bmp) && bmp is JsonValue value && value.TryGetValue<string>(out var encoded))
                {
                    try { images.Add(new { type = "image", mimeType = "image/png", data = Convert.ToBase64String(ScreenPng.ConvertBmp(Convert.FromBase64String(encoded))) }); obj["imageContentIndex"] = images.Count; }
                    catch (Exception ex) when (ex is InvalidDataException or FormatException or OverflowException) { obj["imageEncodingError"] = ex.Message; }
                }
                foreach (var property in obj.ToArray()) Extract(property.Value);
            }
            else if (current is JsonArray array) foreach (var child in array) Extract(child);
        }
        Extract(node);
        var status = node["operation"]?["status"]?.GetValue<string>();
        error |= status is "failed" or "cancelled";
        var content = new List<object> { new { type = "text", text = node.ToJsonString(Wire.Json) } };
        content.AddRange(images);
        return new { content, structuredContent = node, isError = error };
    }

    private async Task SendAsync(TextWriter writer, object message)
    {
        var line = JsonSerializer.Serialize(message, Wire.Json);
        await _outputLock.WaitAsync(_transportCancellation);
        try {
            // Console/pipe writers can block synchronously even through their Async API.
            // Do not let an abandoned client prevent debugger process cleanup on EOF.
            await Task.Run(async () => {
                await writer.WriteLineAsync(line.AsMemory(), _transportCancellation);
                await writer.FlushAsync(_transportCancellation);
            }, _transportCancellation).WaitAsync(TimeSpan.FromSeconds(15), _transportCancellation);
        }
        finally { _outputLock.Release(); }
    }
    private static object Error(JsonElement? id, int code, string message) => new { jsonrpc = "2.0", id, error = new { code, message } };
    private sealed class RpcException(int code, string message) : Exception(message) { internal int Code { get; } = code; }

    private sealed class BoundedLines(TextReader reader)
    {
        private readonly char[] _buffer = new char[4096];
        private int _offset, _length;
        internal async Task<string?> ReadAsync(CancellationToken ct)
        {
            var line = new StringBuilder();
            while (true) {
                if (_offset == _length) {
                    _length = await reader.ReadAsync(_buffer.AsMemory(), ct); _offset = 0;
                    if (_length == 0) return line.Length == 0 ? null : line.ToString();
                }
                var newline = Array.IndexOf(_buffer, '\n', _offset, _length - _offset);
                var count = (newline < 0 ? _length : newline) - _offset;
                if ((long)line.Length + count > 1_048_576) throw new InvalidDataException("Request framing exceeds 1 MiB; closing the local transport.");
                line.Append(_buffer, _offset, count); _offset += count;
                if (newline >= 0) { _offset++; if (line.Length > 0 && line[^1] == '\r') line.Length--; return line.ToString(); }
            }
        }
    }
}
