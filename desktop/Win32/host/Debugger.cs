using System.Text.Json.Nodes;
using FxStudio.Core;

namespace FxStudio.Win32Host;

internal sealed partial class Workspace
{
    private GdbSession? debugger;
    private EmulatorSession? emulator;
    private NativeDebugImage? debugImage;
    private int selectedFrame;
    private readonly Dictionary<int, Installed> installed = [];
    private sealed record Spec(int Id, string File, int Line, string Condition, string Expression, string Access, bool Enabled);
    private sealed record Installed(Spec Spec, string Number);
    private GdbSession Paused => debugger?.State == DebugState.Stopped ? debugger : throw new InvalidOperationException("Pause the target to inspect it.");

    private async Task Start(JsonObject a, CancellationToken ct)
    {
        var item = Artifact;
        await item.VerifyAsync(ct);
        var nativeGdb = First(Text(settings, "gdb"), Path.Combine(root, "runtime", "gdb", "bin", "gdb.exe"));
        var emuPath = First(Text(settings, "emulator"), Path.Combine(root, "runtime", "emulator", "FxEmulator.exe"));
        string sessionFolder;
        bool native = File.Exists(nativeGdb);
        if (!native && (item.LinuxElfPath.Length == 0 || Text(settings, "gdb").Length > 0))
            throw new FileNotFoundException("GDB executable is missing.", nativeGdb);
        try {
            if (native) {
                debugImage = await NativeDebugImage.CreateAsync(item, Work, ct);
                item = debugImage.Artifact;
                sessionFolder = debugImage.DirectoryPath;
            } else {
                sessionFolder = Path.Combine(Path.GetTempPath(), "FxStudio-win32", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(sessionFolder);
            }
            var emu = emulator = new EmulatorSession();
            emu.Output += line => Log("[emu] " + line);
            emu.Exited += code => { if (emulator == emu) Emit("ended", "Emulator (" + code + ")"); };
            await emu.StartAsync(emuPath, item.G1APath, Path.Combine(sessionFolder, "screen.bmp"), ct);
            var gdb = debugger = new GdbSession();
            gdb.Output += line => Log("[gdb] " + line);
            var options = native ? item.CreateNativeGdbOptions(nativeGdb, emu.GdbPort) : item.CreateWslGdbOptions(Project, emu.GdbPort);
            await gdb.StartAsync(options, ct);
            await gdb.InsertBreakpointAsync("main", temporary: true, ct: ct);
            await SyncBreakpoints(a, ct);
            gdb.StateChanged += state => {
                if (debugger != gdb) return;
                if (state is DebugState.Running) Emit("state", "running");
                if (state is DebugState.Exited or DebugState.Faulted) Emit("ended", state.ToString());
            };
            gdb.Stopped += rec => {
                if (debugger != gdb) return;
                var reason = rec.GetString("reason") ?? "stopped";
                selectedFrame = 0;
                if (reason.StartsWith("exited", StringComparison.Ordinal)) Emit("ended", reason);
                else Emit("paused", new { reason, pc = gdb.GetStoppedFrame()?.Address });
            };
            selectedFrame = 0;
            Emit("framebuffer", emu.FramebufferPath);
            await gdb.ContinueAsync(ct);
        } catch { await Stop(); throw; }
    }

    private async Task Stop()
    {
        var gdb = debugger; var emu = emulator; var image = debugImage;
        debugger = null; emulator = null; debugImage = null;
        installed.Clear(); selectedFrame = 0;
        try { if (gdb != null) await gdb.DisposeAsync(); }
        finally {
            try { if (emu != null) await emu.DisposeAsync(); }
            finally {
                if (image != null) await image.DisposeAsync();
                if (emu != null && image == null && emu.FramebufferPath.Length > 0) {
                    var dir = Path.GetDirectoryName(emu.FramebufferPath)!;
                    if (Path.GetDirectoryName(dir) == Path.Combine(Path.GetTempPath(), "FxStudio-win32") && Directory.Exists(dir)) Directory.Delete(dir, true);
                }
                if (gdb != null || emu != null) Emit("state", "idle");
            }
        }
    }

    private async Task SyncBreakpoints(JsonObject a, CancellationToken ct)
    {
        var specs = a["points"]!.AsArray().Select(n => {
            var o = n!.AsObject();
            return new Spec(Num(o, "id"), Text(o, "file"), Num(o, "line"), Text(o, "condition"), Text(o, "expression"),
                Text(o, "access", "write"), o["enabled"]?.GetValue<bool>() ?? true);
        }).ToDictionary(p => p.Id);
        var gdb = Paused;
        foreach (var (id, old) in installed.ToArray()) {
            if (specs.TryGetValue(id, out var spec) && old.Spec == spec) continue;
            await gdb.DeleteBreakpointAsync(old.Number, ct);
            installed.Remove(id);
        }
        foreach (var spec in specs.Values) {
            if (installed.ContainsKey(spec.Id)) continue;
            try {
                var b = spec.Expression.Length > 0 ? await gdb.InsertWatchpointAsync(spec.Expression, spec.Access, ct)
                    : await gdb.InsertBreakpointAsync(gdb.GetBreakpointLocation(spec.File, spec.Line), spec.Condition, ct: ct);
                try { if (!spec.Enabled) await gdb.SetBreakpointEnabledAsync(b.Number, false, ct); }
                catch { await gdb.DeleteBreakpointAsync(b.Number, ct); throw; }
                installed[spec.Id] = new(spec, b.Number);
                Emit("point", new { id = spec.Id, number = b.Number, status = b.Address == "<PENDING>" ? "pending" : "verified" });
            } catch (GdbCommandException ex) { Emit("point", new { id = spec.Id, number = "", status = ex.Message }); }
        }
    }

    private async Task Snapshot(JsonObject a, CancellationToken ct)
    {
        var gdb = Paused;
        var data = new Dictionary<string, object?>();
        async Task Section(string name, Func<Task<object>> read) {
            try { data[name] = await read(); }
            catch (Exception ex) when (ex is not OperationCanceledException) { Log(name + ": " + ex.Message); }
        }
        await Section("stack", async () => {
            var frames = await gdb.GetStackAsync(ct);
            var frame = frames.FirstOrDefault(f => f.Level == selectedFrame) ?? frames.FirstOrDefault();
            if (frame != null) {
                await gdb.SelectFrameAsync(frame.Level, ct);
                data["frame"] = new { frame.Level, frame.Function, frame.LocalPath, frame.Line, frame.Address };
            }
            return frames.Select(f => new { f.Level, f.Function, f.LocalPath, f.File, f.Line, f.Address }).ToArray();
        });
        await Section("locals", async () => await gdb.GetLocalsAsync(ct));
        await Section("registers", async () => await gdb.GetRegistersAsync(ct));
        await Section("disassembly", async () => await gdb.GetDisassemblyAsync("$pc", "$pc+40", ct));
        var watches = new List<object>();
        foreach (var n in a["watches"]?.AsArray() ?? []) {
            var expression = n!.GetValue<string>();
            string value;
            try { value = await gdb.EvaluateAsync(expression, ct); }
            catch (GdbCommandException ex) { value = ex.Message; }
            watches.Add(new { expression, value });
        }
        data["watches"] = watches;
        if (debugger == gdb && gdb.State == DebugState.Stopped) Emit("snapshot", data);
    }

    private async Task DebugCommand(string cmd, JsonObject a, CancellationToken ct)
    {
        switch (cmd) {
            case "pause": if (debugger != null) await debugger.PauseAsync(ct); break;
            case "step": await Paused.StepAsync(ct); break;
            case "next": await Paused.NextAsync(ct); break;
            case "finish": await Paused.FinishAsync(ct); break;
            case "stepi": await Paused.StepInstructionAsync(ct); break;
            case "nexti": await Paused.NextInstructionAsync(ct); break;
            case "runTo":
                var gdb = Paused;
                await gdb.InsertBreakpointAsync(gdb.GetBreakpointLocation(Text(a, "file"), Num(a, "line")), temporary: true, ct: ct);
                await gdb.ContinueAsync(ct); break;
            case "points": await SyncBreakpoints(a, ct); break;
            case "snapshot": await Snapshot(a, ct); break;
            case "frame": await Paused.SelectFrameAsync(Num(a, "level"), ct); selectedFrame = Num(a, "level"); break;
            case "evaluate": Emit("value", await Paused.EvaluateAsync(Text(a, "expression"), ct)); break;
            case "register": await Paused.WriteRegisterAsync(Num(a, "number"), Text(a, "value"), ct); break;
            case "children":
                var session = Paused;
                var expression = Text(a, "expression");
                var rootVariable = await session.CreateVariableObjectAsync(expression, ct);
                try {
                    var variable = rootVariable;
                    var trail = a["trail"]?.AsArray().Select(n => n!.GetValue<int>()).ToArray() ?? [];
                    foreach (var index in trail) {
                        var children = await session.GetVariableChildrenAsync(variable.ObjectName!, ct);
                        if (index < 0 || index >= children.Count) throw new InvalidOperationException("The selected member changed.");
                        variable = children[index];
                    }
                    Emit("children", new { expression, trail, variable, items = variable.Children == 0 ? [] :
                        await session.GetVariableChildrenAsync(variable.ObjectName!, ct) });
                } finally { await session.DeleteVariableObjectAsync(rootVariable.ObjectName!, ct); }
                break;
            case "read":
                int length = Num(a, "count", 128);
                if (length is < 1 or > 65536) throw new ArgumentOutOfRangeException("count", "1–65536");
                var address = Text(a, "address", "$sp");
                Emit("memory", new { address, hex = Convert.ToHexString(await Paused.ReadMemoryAsync(address, length, ct)) }); break;
            case "write":
                var hex = string.Concat(Text(a, "hex").Where(c => !char.IsWhiteSpace(c)));
                if (hex.Length is 0 or > 8192) throw new ArgumentOutOfRangeException("hex", "1–4096 bytes");
                await Paused.WriteMemoryAsync(Text(a, "address"), Convert.FromHexString(hex), ct); break;
            case "key":
                if (emulator == null) throw new InvalidOperationException("No emulator session.");
                await emulator.SendKeyAsync(Text(a, "key"), a["down"]!.GetValue<bool>(), ct); break;
            default: throw new ArgumentException("Unknown operation: " + cmd);
        }
    }
}
