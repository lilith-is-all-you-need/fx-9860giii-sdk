using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using FxStudio.Core;

namespace FxStudio.Automation;

/// <summary>Transport-independent native SDK automation. Each session accepts one operation at a time.</summary>
public sealed partial class AutomationService : IAsyncDisposable
{
    private readonly string _packageRoot;
    private readonly string _dataRoot;
    private readonly ConcurrentDictionary<string, Session> _sessions = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Name,int Version), CommandDefinition> _definitions;
    private readonly SemaphoreSlim _catalogGate = new(1,1);
    private readonly CancellationTokenSource _lifetime = new();
    private readonly object _disposeLock = new();
    private Task? _disposeTask;
    private volatile bool _disposed;
    public IReadOnlyList<CommandDefinition> Commands { get; }
    public event Action<AutomationEvent>? Event;

    public AutomationService(string packageRoot, string? dataRoot = null)
    {
        _packageRoot = Path.GetFullPath(packageRoot);
        _dataRoot = Path.GetFullPath(dataRoot ?? Path.Combine(Path.GetTempPath(), "FxStudio-automation"));
        Commands = CommandCatalog.Create();
        _definitions = Commands.ToDictionary(x => (x.Name,x.Version));
    }

    public Task<object?> ExecuteAsync(string command, JsonElement arguments, CancellationToken ct = default) => ExecuteAsync(command,1,arguments,ct);

    public async Task<object?> ExecuteAsync(string command,int version, JsonElement arguments, CancellationToken ct = default)
    {
        if (_disposed) throw new AutomationException("SERVICE_CLOSED", "The automation service has been disposed.");
        if (!_definitions.TryGetValue((command,version), out var definition)) {
            if(Commands.Any(x=>x.Name==command)) throw new AutomationException("UNSUPPORTED_VERSION","Unsupported command version: "+command+" v"+version);
            throw new AutomationException("UNKNOWN_COMMAND", "Unknown command: " + command);
        }
        try { CommandCatalog.Validate(definition, arguments); ValidateSemantics(command, arguments); }
        catch (AutomationException) { throw; }
        catch (Exception ex) when (ex is InvalidOperationException or FormatException) { throw new AutomationException("INVALID_ARGUMENT",ex.Message); }
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, _lifetime.Token);
        ct = linked.Token; ct.ThrowIfCancellationRequested();
        try {
            if (command == "session.open") return await OpenAsync(arguments, ct);
            if (command == "session.list") return new { sessions = _sessions.Values.Select(Describe).OrderBy(x => x.SessionId).ToArray() };
            var id = Text(arguments,"sessionId");
            if (!_sessions.TryGetValue(id,out var session)) throw new AutomationException("SESSION_NOT_FOUND", "No live session has ID " + id);
            if (!await session.Gate.WaitAsync(0, ct)) throw new AutomationException("BUSY", "The session already has an active operation.", true);
            Interlocked.Exchange(ref session.Busy,1);
            try {
                if (session.Closed) throw new AutomationException("SESSION_NOT_FOUND", "The session is closed.");
                if (command == "session.close") {
                    await StopDebugAsync(session);
                    session.Closed = true; _sessions.TryRemove(id,out _);
                    Publish(session,"session.closed",new { sessionId=id });
                    return new { sessionId=id, closed=true };
                }
                return await ExecuteSessionAsync(session,command,arguments,ct);
            } finally { Interlocked.Exchange(ref session.Busy,0); session.Gate.Release(); }
        } catch (OperationCanceledException) { throw; }
          catch (AutomationException) { throw; }
          catch (Exception ex) { throw Translate(ex); }
    }

    private async Task<SessionInfo> OpenAsync(JsonElement args, CancellationToken ct)
    {
        await _catalogGate.WaitAsync(ct);
        try {
            if (_disposed) throw new AutomationException("SERVICE_CLOSED","The automation service is closed.");
            if (_sessions.Count >= 8) throw new AutomationException("SESSION_LIMIT","Close an existing session before opening another (limit 8).");
            var input = Path.GetFullPath(Text(args,"projectPath"));
            string directory;
            string configPath;
            if (Directory.Exists(input)) { directory=input; configPath=Path.Combine(input,"project.fxide.json"); }
            else if (File.Exists(input) && Path.GetFileName(input).Equals("CMakeLists.txt",StringComparison.OrdinalIgnoreCase)) { directory=Path.GetDirectoryName(input)!; configPath=Path.Combine(directory,"project.fxide.json"); }
            else if (File.Exists(input) && input.EndsWith(".fxide.json",StringComparison.OrdinalIgnoreCase)) { directory=Path.GetDirectoryName(input)!; configPath=input; }
            else throw new AutomationException("PROJECT_NOT_FOUND","Expected a project directory, CMakeLists.txt, or .fxide.json file.");
            var project = File.Exists(configPath) ? await ProjectConfig.LoadAsync(configPath,ct) : new ProjectConfig {
                Name=Path.GetFileName(directory), SourceDirectory=directory, BuildDirectory=Path.Combine(directory,".fxstudio","build")
            };
            if (!File.Exists(Path.Combine(project.SourceDirectory,"CMakeLists.txt"))) throw new AutomationException("PROJECT_NOT_FOUND","Project source does not contain CMakeLists.txt.");
            var sdk = Optional(args,"sdkPath") ?? (string.IsNullOrWhiteSpace(project.NativeSdkDirectory) ? Path.Combine(_packageRoot,"sdk","native") : project.NativeSdkDirectory);
            project = project with { Backend="native", NativeSdkDirectory=Path.GetFullPath(sdk) };
            ct.ThrowIfCancellationRequested();
            var session = new Session(Guid.NewGuid().ToString("N"),input,project);
            session.Builder.Log += line => OnBuildLog(session,line);
            if (!_sessions.TryAdd(session.Id,session)) throw new InvalidOperationException("Session ID collision.");
            Publish(session,"session.opened",Describe(session));
            return Describe(session);
        } finally { _catalogGate.Release(); }
    }

    private async Task<object?> ExecuteSessionAsync(Session s,string command,JsonElement a,CancellationToken ct)
    {
        if (command == "project.inspect") return new { session=Describe(s), cmakePath=Path.Combine(s.Project.SourceDirectory,"CMakeLists.txt"), backend="native",
            missingSdkFiles=MissingSdkFiles(s.Project.NativeSdkDirectory), debugger=FindDebugger(), emulator=FindEmulator() };
        if (command == "build.run") return await BuildAsync(s,a,ct);
        if (command == "debug.launch") return await LaunchAsync(s,Optional(a,"stopAt") ?? "main",ct);
        if (command == "debug.stop") { await StopDebugAsync(s); return Describe(s); }
        if (command == "debug.snapshot") return await SnapshotAsync(s,a,ct);
        if (command == "debug.key") return await KeyAsync(s,a,ct);
        var gdb = s.Gdb ?? throw new AutomationException("NO_DEBUG_SESSION","Launch the debugger first.");
        if (command == "debug.pause") {
            RequireRunning(gdb); await WaitForStopAsync(s,gdb,() => gdb.PauseAsync(ct),ct); return Describe(s);
        }
        RequireStopped(s,gdb);
        switch (command) {
            case "debug.resume": await gdb.ContinueAsync(ct); return Describe(s);
            case "debug.step":
                var mode=Text(a,"mode");
                await WaitForStopAsync(s,gdb,mode switch {
                    "into" => () => gdb.StepAsync(ct), "over" => () => gdb.NextAsync(ct), "out" => () => gdb.FinishAsync(ct),
                    "instruction" => () => gdb.StepInstructionAsync(ct), _ => () => gdb.NextInstructionAsync(ct)
                },ct); return Describe(s);
            case "debug.breakpoint.set":
                var location=Optional(a,"location") ?? gdb.GetBreakpointLocation(ProjectFile(s,Text(a,"file")),Number(a,"line"));
                var bp=await gdb.InsertBreakpointAsync(location,Optional(a,"condition"),Boolean(a,"temporary"),ct); Touch(s); return Breakpoint(bp);
            case "debug.breakpoint.remove": await gdb.DeleteBreakpointAsync(Text(a,"number"),ct); Touch(s); return Describe(s);
            case "debug.breakpoint.enabled": await gdb.SetBreakpointEnabledAsync(Text(a,"number"),Boolean(a,"enabled"),ct); Touch(s); return Describe(s);
            case "debug.watchpoint.set": var watch=await gdb.InsertWatchpointAsync(Text(a,"expression"),Optional(a,"access")??"write",ct); Touch(s); return Breakpoint(watch);
            case "debug.evaluate":
                var expression=Text(a,"expression"); var value=await gdb.EvaluateAsync(expression,ct); Touch(s);
                return new { sessionId=s.Id,revision=Revision(s),expression,value };
            case "debug.variable.children": return await ChildrenAsync(gdb,Text(a,"expression"),ct);
            case "debug.frame.select": await gdb.SelectFrameAsync(Number(a,"level"),ct); lock(s.Sync) s.SelectedFrame=Number(a,"level"); Touch(s); return Describe(s);
            case "debug.register.write": await gdb.WriteRegisterAsync(Number(a,"number"),Text(a,"value"),ct); Touch(s); return Describe(s);
            case "debug.memory.read":
                var address=Text(a,"address"); var data=await gdb.ReadMemoryAsync(address,Number(a,"count"),ct);
                return new { sessionId=s.Id,revision=Revision(s),address,count=data.Length,hex=Convert.ToHexStringLower(data) };
            case "debug.memory.write":
                var bytes=Convert.FromHexString(string.Concat(Text(a,"hex").Where(c => !char.IsWhiteSpace(c))));
                await gdb.WriteMemoryAsync(Text(a,"address"),bytes,ct); Touch(s); return new { sessionId=s.Id,revision=Revision(s),written=bytes.Length };
            case "debug.disassemble":
                var begin=await AddressAsync(gdb,Text(a,"start"),ct); var end=await AddressAsync(gdb,Text(a,"end"),ct);
                if (end<=begin || end-begin>65536 || begin>uint.MaxValue || end>0x1_0000_0000UL) throw new AutomationException("INVALID_ARGUMENT","Disassembly range must be 1–65536 bytes within the 32-bit target address space.");
                return new { sessionId=s.Id,revision=Revision(s),instructions=await gdb.GetDisassemblyAsync($"0x{begin:x}",$"0x{end:x}",ct) };
            default: throw new AutomationException("UNKNOWN_COMMAND",command);
        }
    }

    private async Task<object> BuildAsync(Session s,JsonElement args,CancellationToken ct)
    {
        if (s.Gdb != null || s.Emulator != null) throw new AutomationException("DEBUG_ACTIVE","Stop the debugger before building.");
        s.Artifact=null; Touch(s);
        var missing=MissingSdkFiles(s.Project.NativeSdkDirectory);
        if (missing.Length>0) throw new AutomationException("SDK_MISSING","Native SDK files are missing: " + string.Join(", ",missing));
        var configuration=Enum.Parse<BuildConfiguration>(Optional(args,"configuration")??"Debug");
        lock(s.Sync) { s.Diagnostics.Clear(); s.DiagnosticsTruncated=false; }
        State(s,"Building");
        try {
            s.Artifact=await s.Builder.BuildAsync(s.Project,configuration,ct); Touch(s);
            State(s,"Open");
            DiagnosticInfo[] diagnostics; bool truncated;
            lock(s.Sync) { diagnostics=s.Diagnostics.ToArray(); truncated=s.DiagnosticsTruncated; }
            var result=new { sessionId=s.Id,revision=Revision(s),artifact=Artifact(s.Artifact),diagnostics,diagnosticsTruncated=truncated };
            Publish(s,"build.completed",result); return result;
        } catch(Exception ex) {
            Publish(s,"build.failed",new { code=ex is OperationCanceledException?"CANCELLED":Translate(ex).Code,message=Limit(ex.Message,4096) }); throw;
        } finally { State(s,"Open"); }
    }

    private async Task<object> LaunchAsync(Session s,string stopAt,CancellationToken ct)
    {
        if (s.Gdb != null || s.Emulator != null) throw new AutomationException("DEBUG_ACTIVE","Stop the current debug session before launching again.");
        var artifact=s.Artifact ?? throw new AutomationException("BUILD_REQUIRED","Build this session successfully before launching.");
        var gdbPath=FindDebugger() ?? throw new AutomationException("DEBUGGER_MISSING","Bundled native GDB is missing under runtime/gdb/bin.");
        var emulatorPath=FindEmulator() ?? throw new AutomationException("EMULATOR_MISSING","Bundled emulator is missing under runtime/emulator.");
        State(s,"Starting");
        try {
            s.Image=await NativeDebugImage.CreateAsync(artifact,_dataRoot,ct);
            var emulator=new EmulatorSession(); s.Emulator=emulator;
            emulator.Output += line => Publish(s,"emulator.output",new { text=Limit(line,8192) });
            emulator.Exited += code => { if(ReferenceEquals(s.Emulator,emulator)) { State(s,"Exited"); Publish(s,"emulator.exited",new { exitCode=code }); } };
            await emulator.StartAsync(emulatorPath,s.Image.Artifact.G1APath,Path.Combine(s.Image.DirectoryPath,"screen.bmp"),ct);
            var gdb=new GdbSession(); s.Gdb=gdb;
            gdb.Output += text => Publish(s,"debug.output",new { text=Limit(text,8192) });
            gdb.StateChanged += state => { if(ReferenceEquals(s.Gdb,gdb) && state!=DebugState.Stopped) State(s,state.ToString()); };
            gdb.Stopped += record => {
                if(!ReferenceEquals(s.Gdb,gdb)) return;
                StopInfo stop;
                lock(s.Sync) {
                    s.SelectedFrame=0; var revision=++s.Revision;
                    s.State=gdb.State.ToString();
                    stop=new(record.GetString("reason"),record.GetString("bkptno"),record.GetString("signal-name"),record.GetString("signal-meaning"),Frame(gdb.GetStoppedFrame()),revision,DateTimeOffset.UtcNow);
                    s.LastStop=stop;
                }
                Publish(s,"debug.state",new { state=gdb.State.ToString(),revision=stop.Revision });
                Publish(s,"debug.stopped",stop);
            };
            await gdb.StartAsync(s.Image.Artifact.CreateNativeGdbOptions(gdbPath,emulator.GdbPort),ct);
            // Even apparently simple C++ paths can invoke overloaded operators. Read operations
            // must never call the inferior; keep the policy enabled for the entire session.
            await gdb.CommandAsync("-gdb-set may-call-functions off",ct);
            await gdb.InsertBreakpointAsync(stopAt,temporary:true,ct:ct);
            await WaitForStopAsync(s,gdb,() => gdb.ContinueAsync(ct),ct);
            return Describe(s);
        } catch { await StopDebugAsync(s); throw; }
    }

    private static async Task WaitForStopAsync(Session s,GdbSession gdb,Func<Task<MiRecord>> operation,CancellationToken ct)
    {
        var stop=new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Stopped(MiRecord _) => stop.TrySetResult(true);
        void Changed(DebugState state) { if(state is DebugState.Exited or DebugState.Faulted or DebugState.Disposed) stop.TrySetException(new AutomationException("TARGET_EXITED","The debug process ended before stopping.")); }
        gdb.Stopped+=Stopped; gdb.StateChanged+=Changed;
        try {
            await operation();
            await stop.Task.WaitAsync(TimeSpan.FromSeconds(30),ct);
        } catch (TimeoutException) { throw new AutomationException("STOP_TIMEOUT","No target stop was received within 30 seconds. The target may still be running; use debug.pause.",true); }
        finally { gdb.Stopped-=Stopped; gdb.StateChanged-=Changed; }
    }

    private async Task StopDebugAsync(Session s)
    {
        var gdb=s.Gdb; var emulator=s.Emulator; var image=s.Image;
        s.Gdb=null; s.Emulator=null; s.Image=null;
        if (gdb is null && emulator is null && image is null) return;
        State(s,"Stopping");
        try { try { if(gdb != null) await gdb.DisposeAsync(); } finally { if(emulator != null) await emulator.DisposeAsync(); } }
        finally { if(image != null) await image.DisposeAsync(); lock(s.Sync) { s.LastStop=null; s.SelectedFrame=0; } State(s,"Open"); }
    }

    private async Task<object> KeyAsync(Session s,JsonElement args,CancellationToken ct)
    {
        var gdb=s.Gdb ?? throw new AutomationException("NO_DEBUG_SESSION","Launch the debugger first."); RequireRunning(gdb);
        var emu=s.Emulator ?? throw new AutomationException("EMULATOR_MISSING","No emulator is attached.");
        var key=Text(args,"key"); var action=Text(args,"action"); var duration=args.TryGetProperty("durationMs",out var d)?d.GetInt32():120;
        if(action=="press") {
            try { await emu.SendKeyAsync(key,true,ct); await Task.Delay(duration,ct); }
            finally { if(emu.IsAlive) { using var release=new CancellationTokenSource(TimeSpan.FromSeconds(2)); await emu.SendKeyAsync(key,false,release.Token); } }
        } else await emu.SendKeyAsync(key,action=="down",ct);
        Touch(s); return new { sessionId=s.Id,revision=Revision(s),key,action };
    }

    private static async Task<object> ChildrenAsync(GdbSession gdb,string expression,CancellationToken ct)
    {
        var root=await gdb.CreateVariableObjectAsync(expression,ct);
        try {
            var children=new List<VariableInfo>();
            foreach(var child in await gdb.GetVariableChildrenAsync(root.ObjectName!,ct)) {
                // C++ access groups are GDB synthetic nodes, not addressable expression paths.
                if(child.Type is null && child.Name is "public" or "protected" or "private" && child.ObjectName is not null)
                    children.AddRange((await gdb.GetVariableChildrenAsync(child.ObjectName,ct)).Select(Variable));
                else children.Add(Variable(child));
            }
            return new { expression,variable=Variable(root) with { Children=children.Count },children=children.ToArray() };
        }
        finally { if(root.ObjectName is { } name && gdb.IsAlive) { using var cleanup=new CancellationTokenSource(TimeSpan.FromSeconds(2)); try { await gdb.DeleteVariableObjectAsync(name,cleanup.Token); } catch { } } }
    }

    private string? FindDebugger() => new[] { "sh-elf-gdb.exe", "gdb.exe", "gdb-multiarch.exe" }.Select(x => Path.Combine(_packageRoot,"runtime","gdb","bin",x)).FirstOrDefault(File.Exists);
    private string? FindEmulator() { var path=Path.Combine(_packageRoot,"runtime","emulator","FxEmulator.exe"); return File.Exists(path)?path:null; }
    private static string[] MissingSdkFiles(string sdk) => new[] { "bin/sh-elf-gcc.exe","bin/sh-elf-g++.exe","bin/fxgxa.exe","host/python/python.exe","host/cmake/bin/cmake.exe","host/ninja/ninja.exe","service/build-native.py","service/build-project.py","service/compiler-launcher.py" }.Select(x=>Path.Combine(sdk,x)).Where(x=>!File.Exists(x)).ToArray();
    private static string ProjectFile(Session s,string file) => Path.GetFullPath(file,s.Project.SourceDirectory);
    private static void RequireStopped(Session s,GdbSession gdb) { lock(s.Sync) if(gdb.State!=DebugState.Stopped || s.State!="Stopped") throw new AutomationException("NOT_STOPPED","Pause the target and wait for its stop event before this operation.",gdb.State is DebugState.Running or DebugState.Stopped); }
    private static void RequireRunning(GdbSession gdb) { if(gdb.State!=DebugState.Running) throw new AutomationException("NOT_RUNNING","The target must be running for this operation."); }
    private static FrameInfo? Frame(DebugFrame? f) => f is null?null:new(f.Level,f.Address,f.Function,f.FullName??f.File,f.LocalPath,f.Line);
    private static VariableInfo Variable(DebugVariable v) => new(v.Name,v.Value,v.Type,v.Children,v.IsArgument);
    private static BreakpointInfo Breakpoint(DebugBreakpoint b) => new(b.Number,b.Type,b.Enabled,b.Address,b.File,b.Line,b.Condition);
    private static ArtifactInfo Artifact(BuildArtifact a) { long? bytes; try { bytes=a.G1ASize; } catch(IOException) { bytes=null; } return new(a.ElfPath,a.G1APath,a.ManifestPath,a.Configuration.ToString(),a.ElfSha256,a.G1ASha256,bytes); }
    private static SessionInfo Describe(Session s) { lock(s.Sync) return new(s.Id,s.Project.Name,s.ProjectPath,s.Project.SourceDirectory,s.Project.BuildDirectory,s.Project.NativeSdkDirectory,s.State,s.Revision,Volatile.Read(ref s.Busy)!=0,s.SelectedFrame,s.LastStop,s.Artifact is {} a?Artifact(a):null); }
    private static long Revision(Session s) { lock(s.Sync) return s.Revision; }
    private static void Touch(Session s) { lock(s.Sync) s.Revision++; }
    private void State(Session s,string state) { long revision; lock(s.Sync) { if(s.State==state)return; s.State=state; revision=++s.Revision; } Publish(s,"debug.state",new { state,revision }); }
    private void Publish(Session s,string kind,object? data) { if(Event is not {} handlers)return; foreach(Action<AutomationEvent> handler in handlers.GetInvocationList()) { try { handler(new(s.Id,kind,data)); } catch { } } }
    private static string Limit(string text,int max) => text.Length<=max?text:text[..max]+"… [truncated]";
    private static string Text(JsonElement value,string key) => value.GetProperty(key).GetString()!;
    private static string? Optional(JsonElement value,string key) => value.TryGetProperty(key,out var v)?v.GetString():null;
    private static int Number(JsonElement value,string key) => value.GetProperty(key).GetInt32();
    private static bool Boolean(JsonElement value,string key) => value.TryGetProperty(key,out var v)&&v.GetBoolean();
    private static AutomationException Translate(Exception ex) => ex switch {
        AutomationException known=>known,
        GdbCommandException => new("GDB_ERROR",Limit(ex.Message,4096)),
        ArtifactPairMismatchException=>new("ARTIFACT_MISMATCH",Limit(ex.Message,4096)),
        BuildException=>new("BUILD_FAILED",Limit(ex.Message,4096)),
        TimeoutException=>new("TIMEOUT",Limit(ex.Message,4096),true),
        FileNotFoundException or DirectoryNotFoundException=>new("FILE_NOT_FOUND",Limit(ex.Message,4096)),
        UnauthorizedAccessException=>new("ACCESS_DENIED",Limit(ex.Message,4096)),
        JsonException or ArgumentException or FormatException=>new("INVALID_ARGUMENT",Limit(ex.Message,4096)),
        InvalidDataException=>new("INVALID_DATA",Limit(ex.Message,4096)),
        EndOfStreamException=>new("PROCESS_EXITED",Limit(ex.Message,4096)),
        IOException=>new("IO_ERROR",Limit(ex.Message,4096)),
        _=>new("OPERATION_FAILED",Limit(ex.Message,4096))
    };

    public ValueTask DisposeAsync() { lock(_disposeLock) return new(_disposeTask??=DisposeCoreAsync()); }
    private async Task DisposeCoreAsync()
    {
        _disposed=true; await _lifetime.CancelAsync();
        await _catalogGate.WaitAsync();
        Session[] sessions;
        try { sessions=_sessions.Values.ToArray(); } finally { _catalogGate.Release(); }
        List<Exception>? errors=null;
        foreach(var session in sessions) {
            await session.Gate.WaitAsync();
            try { await StopDebugAsync(session); }
            catch(Exception ex) { (errors??=[]).Add(ex); }
            finally { session.Closed=true; _sessions.TryRemove(session.Id,out _); session.Gate.Release(); }
        }
        if(errors is not null) throw new AggregateException("Some session resources could not be cleaned up.",errors);
    }
    private sealed class Session(string id,string path,ProjectConfig project)
    {
        public string Id { get; }=id;
        public string ProjectPath { get; }=path;
        public ProjectConfig Project { get; }=project;
        public BuildService Builder { get; }=new();
        public SemaphoreSlim Gate { get; }=new(1,1);
        public object Sync { get; }=new();
        public BuildArtifact? Artifact;
        public GdbSession? Gdb;
        public EmulatorSession? Emulator;
        public NativeDebugImage? Image;
        public bool Closed;
        public int Busy;
        public string State="Open";
        public long Revision=1;
        public int SelectedFrame;
        public StopInfo? LastStop;
        public List<DiagnosticInfo> Diagnostics { get; }=[];
        public bool DiagnosticsTruncated;
    }
}
