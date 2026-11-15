using System.Text.Json;
using System.Text.RegularExpressions;

namespace FxStudio.Automation;

internal static class CommandCatalog
{
    private static Dictionary<string, object?> S(int max = 2048) => new() { ["type"] = "string", ["minLength"] = 1, ["maxLength"] = max };
    private static Dictionary<string, object?> E(params string[] values) => new() { ["type"] = "string", ["enum"] = values };
    private static Dictionary<string, object?> I(int min, int max) => new() { ["type"] = "integer", ["minimum"] = min, ["maximum"] = max };
    private static Dictionary<string, object?> B() => new() { ["type"] = "boolean" };
    private static Dictionary<string, object?> P(string pattern) { var schema=S(); schema["pattern"]="^"+pattern+"$"; return schema; }
    private static Dictionary<string, object?> A(object items, int max) => new() { ["type"] = "array", ["items"] = items, ["maxItems"] = max };
    private static CommandDefinition C(string name, string effect, string description, Dictionary<string, object?> properties,
        string[]? required = null, bool session = true)
    {
        if (session) properties["sessionId"] = S(64);
        var needs = (required ?? []).Concat(session ? ["sessionId"] : Array.Empty<string>()).ToArray();
        return new(name, 1, description, effect, JsonSerializer.SerializeToElement(new Dictionary<string, object?> {
            ["type"] = "object", ["properties"] = properties, ["required"] = needs, ["additionalProperties"] = false
        }));
    }

    public static IReadOnlyList<CommandDefinition> Create()
    {
        var result = new List<CommandDefinition> {
            C("session.open", "mutate", "Open a native CMake project without changing its configuration file.", new() { ["projectPath"] = S(32768), ["sdkPath"] = S(32768) }, ["projectPath"], false),
            C("session.close", "mutate", "Close a session and clean up only its own debugger and emulator processes.", new()),
            C("session.list", "read", "List live sessions, including their current operation state.", new(), session:false),
            C("project.inspect", "read", "Inspect project paths, native SDK availability and the current artifact.", new()),
            C("build.run", "execute", "Build with the native SDK and verify the produced ELF/G1A pair. Debug is the default.", new() { ["configuration"] = E("Debug", "Release") }),
            C("debug.launch", "execute", "Freeze and verify the built image, launch the real SuperH target and stop at main (or stopAt).", new() { ["stopAt"] = S() }),
            C("debug.stop", "execute", "Stop this session's debugger and emulator. Safe when already stopped.", new()),
            C("debug.resume", "execute", "Resume a paused SuperH target.", new()),
            C("debug.pause", "execute", "Interrupt a running target and wait for its actual stop.", new()),
            C("debug.step", "execute", "Step and wait for an actual target stop; mode is required.", new() { ["mode"] = E("into", "over", "out", "instruction", "nextInstruction") }, ["mode"]),
            C("debug.breakpoint.set", "mutate", "Set a breakpoint using exactly location OR file and line; target must be paused.", new() { ["location"] = S(), ["file"] = S(32768), ["line"] = I(1,10000000), ["condition"] = new Dictionary<string,object?> { ["type"]="string", ["maxLength"]=2048 }, ["temporary"] = B() }),
            C("debug.breakpoint.remove", "mutate", "Remove a target breakpoint by its GDB number.", new() { ["number"] = S(32) }, ["number"]),
            C("debug.breakpoint.enabled", "mutate", "Enable or disable a breakpoint.", new() { ["number"] = S(32), ["enabled"] = B() }, ["number", "enabled"]),
            C("debug.watchpoint.set", "mutate", "Set a data watchpoint while paused; access defaults to write.", new() { ["expression"] = S(), ["access"] = E("write", "read", "access") }, ["expression"]),
            C("debug.evaluate", "mutate", "Evaluate a GDB expression, including target assignments and arithmetic. Inferior function calls are disabled for this session.", new() { ["expression"] = S() }, ["expression"]),
            C("debug.variable.children", "read", "Return immediate children of a strict variable/register path; calls, assignment and arithmetic are rejected.", new() { ["expression"] = P(AutomationService.VariablePathPattern) }, ["expression"]),
            C("debug.frame.select", "mutate", "Select a paused call-stack frame for subsequent expressions and locals.", new() { ["level"] = I(0,127) }, ["level"]),
            C("debug.register.write", "mutate", "Write a real target register while paused.", new() { ["number"] = I(0,1023), ["value"] = S(256) }, ["number", "value"]),
            C("debug.memory.read", "read", "Read up to 65536 bytes while paused. Address is numeric or a variable/register path with an optional +/- constant.", new() { ["address"] = P(AutomationService.AddressPattern), ["count"] = I(1,65536) }, ["address", "count"]),
            C("debug.memory.write", "mutate", "Write hex bytes to target memory while paused, up to 65536 bytes.", new() { ["address"] = S(), ["hex"] = S(196608) }, ["address", "hex"]),
            C("debug.disassemble", "read", "Disassemble 1–65536 bytes while paused. Addresses use the restricted, side-effect-free address grammar.", new() { ["start"] = P(AutomationService.AddressPattern), ["end"] = P(AutomationService.AddressPattern) }, ["start", "end"]),
            C("debug.key", "execute", "Send a calculator key while running. Press releases the key even when cancelled; default duration is 120ms.", new() { ["key"] = S(32), ["action"] = E("press", "down", "up"), ["durationMs"] = I(1,2000) }, ["key", "action"]),
            C("debug.snapshot", "read", "Read a snapshot without automatically pausing. Expressions accept only strict variable/register paths. Running snapshots contain only status/screen and consistent=false.", new() { ["include"] = A(E("stack", "locals", "registers", "breakpoints", "screen"),5), ["expressions"] = A(P(AutomationService.VariablePathPattern),32) })
        };
        var index = result.FindIndex(x => x.Name == "debug.breakpoint.set");
        var schema = JsonSerializer.Deserialize<Dictionary<string,object?>>(JsonSerializer.Serialize(result[index].InputSchema))!;
        schema["oneOf"] = new object[] {
            new { required = new[]{"location"}, not = new { anyOf = new[]{new { required = new[]{"file"}},new { required = new[]{"line"}}}}},
            new { required = new[]{"file","line"}, not = new { required = new[]{"location"}}}
        };
        result[index] = result[index] with { InputSchema = JsonSerializer.SerializeToElement(schema) };
        return result.AsReadOnly();
    }

    public static void Validate(CommandDefinition definition, JsonElement value)
    {
        var schema = (JsonElement)definition.InputSchema;
        ValidateValue(schema, value, "arguments");
        if (definition.Name == "debug.breakpoint.set") {
            var location = value.TryGetProperty("location",out _);
            var file = value.TryGetProperty("file",out _); var line = value.TryGetProperty("line",out _);
            if (location ? file || line : !file || !line) Invalid("Use exactly location OR file and line.");
        }
        if (value.TryGetProperty("number", out var number) && number.ValueKind == JsonValueKind.String &&
            !Regex.IsMatch(number.GetString()!, @"^\d+(\.\d+)*$", RegexOptions.CultureInvariant)) Invalid("Invalid breakpoint number.");
    }
    private static void ValidateValue(JsonElement schema, JsonElement value, string path)
    {
        var type = schema.GetProperty("type").GetString();
        if (type == "object") {
            if (value.ValueKind != JsonValueKind.Object) Invalid(path + " must be an object.");
            var properties = schema.GetProperty("properties"); var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject()) {
                if (!seen.Add(property.Name)) Invalid("Duplicate argument: " + property.Name);
                if (!properties.TryGetProperty(property.Name, out var propertySchema)) Invalid("Unknown argument: " + property.Name);
                ValidateValue(propertySchema, property.Value, path + "." + property.Name);
            }
            foreach (var required in schema.GetProperty("required").EnumerateArray())
                if (!value.TryGetProperty(required.GetString()!, out _)) Invalid("Missing argument: " + required.GetString());
        } else if (type == "string") {
            if (value.ValueKind != JsonValueKind.String) Invalid(path + " must be a string.");
            var text = value.GetString()!;
            if (text.Contains('\0')) Invalid(path + " must not contain NUL.");
            if (schema.TryGetProperty("minLength", out var min) && string.IsNullOrWhiteSpace(text)) Invalid(path + " must not be blank.");
            if (schema.TryGetProperty("maxLength", out var max) && text.Length > max.GetInt32()) Invalid(path + " is too long.");
            if (schema.TryGetProperty("enum",out var choices) && !choices.EnumerateArray().Any(x => x.GetString() == text)) Invalid(path + " has an unsupported value.");
        } else if (type == "integer") {
            if (value.ValueKind!=JsonValueKind.Number || !value.TryGetInt32(out var n) || n < schema.GetProperty("minimum").GetInt32() || n > schema.GetProperty("maximum").GetInt32()) Invalid(path + " is outside its integer bounds.");
        } else if (type == "boolean") {
            if (value.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) Invalid(path + " must be boolean.");
        } else if (type == "array") {
            if (value.ValueKind != JsonValueKind.Array) Invalid(path + " must be an array.");
            if (value.GetArrayLength() > schema.GetProperty("maxItems").GetInt32()) Invalid(path + " contains too many items.");
            foreach (var item in value.EnumerateArray()) ValidateValue(schema.GetProperty("items"),item,path+"[]");
        }
    }
    private static void Invalid(string message) => throw new AutomationException("INVALID_ARGUMENT",message);
}
