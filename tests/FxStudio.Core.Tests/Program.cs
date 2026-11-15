using System.Reflection;
using System.Buffers.Binary;
using System.Text;
using FxStudio.Core;

if (args.Contains("--mi-fixture"))
{
    await RunFixtureAsync();
    return;
}

if (args.Length > 0 && args[0] is "--integration" or "--source-cas01")
{
    await RunIntegrationAsync(args);
    return;
}
if (args.Length > 0 && args[0] == "--transport")
{
    await RunTransportAsync(args);
    return;
}
if (args.Length == 3 && args[0] == "--verify-pair")
{
    var pair = await ArtifactPairVerifier.VerifyAsync(args[1], args[2]);
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(pair, new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    Environment.ExitCode = pair.IsMatch ? 0 : 1;
    return;
}
if (args.Length == 3 && args[0] == "--native-contract")
{
    await NativeBuildContract.RunAsync(args[1], args[2]);
    return;
}

var passed = new List<string>();
void Check(bool condition, string description)
{
    if (!condition) throw new Exception("FAILED: " + description);
    passed.Add(description);
}
void Reject(string input, string description)
{
    try { MiParser.Parse(input); throw new Exception("Malformed input accepted: " + input); }
    catch (MiParseException) { passed.Add(description); }
}

Check(MiParser.Parse("(gdb) ") is null, "prompt ignored");
Check(MiParser.Parse("") is null, "empty line ignored");
var nested = MiParser.Parse("23^done,stack=[frame={level=\"0\",addr=\"0x00300450\",func=\"change_counter\",args=[{name=\"p\",value=\"0x08100100\"}],file=\"src/main.cpp\",fullname=\"/mnt/c/工作/src/main.cpp\",line=\"27\"},frame={level=\"1\",func=\"main\"}]")!;
Check(nested.Token == 23 && nested.Class == "done", "command token retained");
Check(nested.Results["stack"]!.Items.Count == 2, "repeated frame results retained in list");
Check(nested.Results["stack"]!.Items[0]["frame"]!["args"]!.Items[0].GetString("value") == "0x08100100", "nested argument values");
Check(nested.Results["stack"]!.Items[0]["frame"]!.GetString("fullname")!.Contains("工作"), "literal Unicode retained");
var mixed = MiParser.Parse("^done,x=[\"a\",name=\"b\",{v=\"c\"},[\"d\"]],x=\"repeat\"")!;
Check(mixed.Results.GetAll("x").Count() == 2, "repeated tuple fields retained");
Check(mixed.Results["x"]!.Items[1].GetString("name") == "b", "MI result list entry preserved");
Check(mixed.Results["x"]!.Items[3].Items[0].Text == "d", "nested value list preserved");
var stream = MiParser.Parse("~\"line\\nquote \\\" slash \\\\ tab\\t UTF8 \\344\\270\\255\\346\\226\\207\\n\"")!;
Check(stream.StreamText == "line\nquote \" slash \\ tab\t UTF8 中文\n", "C escapes and escaped UTF8 decoded");
var roundtrip = "C:\\path with spaces\\lilith's\n中文\t\0\"";
Check(MiParser.Parse("~" + MiValue.Quote(roundtrip))!.StreamText == roundtrip, "quoted path roundtrip including control characters");
Check(MiParser.Parse("&\"\\x41\\101\"")!.StreamText == "AA", "hex and octal byte escapes");
Check(MiParser.Parse("*stopped,reason=\"watchpoint-trigger\",wpt={number=\"3\",exp=\"counter.value\"},value={old=\"1\",new=\"2\"}")!.Results["value"]!.GetString("new") == "2", "watchpoint async record decoded");
Check(MiParser.Parse("=thread-group-exited,id=\"i1\",exit-code=\"0\"")!.Kind == '=', "notify record decoded");
Check(MiParser.Parse("+download,section=\".text\",section-sent=\"5\"")!.Kind == '+', "status record decoded");
Check(MiParser.Parse("1^error,msg=\"No symbol \\\"x\\\" in current context.\"")!.GetString("msg")!.Contains("\"x\""), "error record quote decoded");
var multiLocation = MiParser.Parse("20^done,bkpt={number=\"2\",type=\"breakpoint\",addr=\"<MULTIPLE>\"},{number=\"2.1\",addr=\"0x00306de8\",line=\"766\"},{number=\"2.2\",addr=\"0x00306efc\",line=\"799\"}")!;
Check(multiLocation.Results.GetAll("").Count() == 2 && multiLocation.Results.GetString("none") is null,
    "real GDB MI2 anonymous multi-location breakpoint tuples preserved");
Reject("^done,foo={", "unterminated tuple rejected");
Reject("^done,foo=[\"a\",]", "trailing list comma rejected");
Reject("~\"bad\\q\"", "invalid C escape rejected");
Reject("~\"unterminated", "unterminated string rejected");
Reject("^done,foo=notquoted", "unquoted constant rejected");
Reject("^done extra", "trailing record garbage rejected");
Reject("999999999999999999999999^done", "overflow token rejected");
Reject("^done,x=" + string.Concat(Enumerable.Repeat("{a=", 130)) + "\"x\"" + new string('}', 130), "excessive nesting rejected");

var (fixtureElf, fixtureG1a) = CreateArtifactFixture();
var pairFixture = ArtifactPairVerifier.Verify(fixtureElf, fixtureG1a);
Check(ArtifactPairVerifier.Verify(fixtureElf, new byte[2_000_001]).Issues.Any(x => x.Code == "g1a-size-limit"),
    "G1A above the recorded 2,000,000-byte deployment budget is rejected");
Check(pairFixture.IsMatch && pairFixture.ComparedBytes == 48 && pairFixture.PayloadBytes == 64,
    "ELF/G1A pairing maps data by LMA, accepts zero padding and excludes BSS");
var changedPayload = fixtureG1a.ToArray(); changedPayload[520] ^= 0x80;
var mismatch = ArtifactPairVerifier.Verify(fixtureElf, changedPayload).Issues.Single(x => x.Code == "payload-mismatch");
Check(mismatch.G1AOffset == 520 && mismatch.ElfOffset == 264 && mismatch.Address == 0x00300208,
    "pair mismatch reports exact ELF/G1A offsets and target address");
var wrongMachine = fixtureElf.ToArray(); BinaryPrimitives.WriteUInt16BigEndian(wrongMachine.AsSpan(18, 2), 3);
Check(ArtifactPairVerifier.Verify(wrongMachine, fixtureG1a).Issues.Any(x => x.Code == "elf-machine"), "non-SuperH ELF rejected");
var wrongEndian = fixtureElf.ToArray(); wrongEndian[5] = 1;
Check(ArtifactPairVerifier.Verify(wrongEndian, fixtureG1a).Issues.Any(x => x.Code == "elf-endian"), "little-endian ELF rejected");
var badSegment = fixtureElf.ToArray(); BinaryPrimitives.WriteUInt32BigEndian(badSegment.AsSpan(56, 4), 0xfffffff0);
Check(ArtifactPairVerifier.Verify(badSegment, fixtureG1a).Issues.Any(x => x.Code == "elf-segment-bounds"), "overflowing segment bounds rejected");
var overlap = fixtureElf.ToArray(); BinaryPrimitives.WriteUInt32BigEndian(overlap.AsSpan(96, 4), 0x00300210);
Check(ArtifactPairVerifier.Verify(overlap, fixtureG1a).Issues.Any(x => x.Code == "elf-segment-overlap"), "overlapping ROM segments rejected");
var nonzeroGap = fixtureG1a.ToArray(); nonzeroGap[552] = 0xff;
Check(ArtifactPairVerifier.Verify(fixtureElf, nonzeroGap).Issues.Any(x => x.Code == "payload-gap-data"), "unmapped nonzero G1A bytes rejected");
var truncatedElf = fixtureElf.AsSpan(0, 280).ToArray();
Check(ArtifactPairVerifier.Verify(truncatedElf, fixtureG1a).Issues.Any(x => x.Code == "elf-segment-bounds"), "truncated ELF payload rejected");
var invalidHeader = fixtureG1a.ToArray(); invalidHeader[0] ^= 1;
Check(ArtifactPairVerifier.Verify(fixtureElf, invalidHeader).Issues.Any(x => x.Code == "g1a-magic"), "invalid inverted G1A header rejected");
var extraPayload = new byte[fixtureG1a.Length + 16]; fixtureG1a.CopyTo(extraPayload, 0); WriteG1AHeader(extraPayload);
Check(ArtifactPairVerifier.Verify(fixtureElf, extraPayload).Issues.Any(x => x.Code == "payload-extent"), "extra zero payload beyond ELF load extent rejected");
ArtifactPairVerifier.CheckExpectedSha256(pairFixture.ElfSha256, pairFixture.ElfSha256.ToUpperInvariant(), "ELF");
passed.Add("manifest SHA comparison accepts equivalent uppercase hashes");
try { ArtifactPairVerifier.CheckExpectedSha256(pairFixture.ElfSha256, new string('0', 64), "ELF"); throw new Exception("Wrong hash accepted"); }
catch (InvalidDataException) { passed.Add("modified artifact SHA mismatch rejected"); }
try { ArtifactPairVerifier.CheckExpectedSha256(pairFixture.ElfSha256, "wrong", "ELF"); throw new Exception("Malformed hash accepted"); }
catch (InvalidDataException) { passed.Add("malformed manifest SHA rejected"); }

var fixtureExecutable = Environment.ProcessPath!;
var fixtureArguments = new List<string>();
if (Path.GetFileNameWithoutExtension(fixtureExecutable).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
    fixtureArguments.Add(Assembly.GetExecutingAssembly().Location);
fixtureArguments.Add("--mi-fixture");
GdbLaunchOptions FixtureOptions() => new()
{
    ExecutablePath = fixtureExecutable, Arguments = fixtureArguments, ElfPath = "C:/spaces and 'quote'/probe.elf",
    Port = 1234, SourceMappings = [new("/staging", "C:/original"), new("/staging/deep", "C:/specific")],
    CommandTimeout = TimeSpan.FromSeconds(3)
};
await using (var session = new GdbSession())
{
    var stoppedEvents = 0;
    session.Stopped += _ => Interlocked.Increment(ref stoppedEvents);
    await session.StartAsync(FixtureOptions());
    Check(session.State == DebugState.Stopped, "session starts from real MI stopped record");
    Check(session.GetStoppedFrame()?.LocalPath == "C:/specific/main.cpp", "longest source mapping chosen");
    Check(session.MapSourcePath("/staging-other/a") == "/staging-other/a", "source mapping respects path boundary");
    Check(session.GetBreakpointLocation("c:\\specific\\main.cpp", 27) == "/staging/deep/main.cpp:27", "editor breakpoint maps back to DWARF path");
    var one = session.CommandAsync("-test-order-one");
    var two = session.CommandAsync("-test-order-two");
    var three = session.CommandAsync("-test-order-three");
    var results = await Task.WhenAll(one, two, three);
    Check(results.Select(r => r.GetString("value")).SequenceEqual(new[] { "one", "two", "three" }), "out-of-order responses correlate by token");
    Check(stoppedEvents == 2 && session.State == DebugState.Stopped, "async stop processed amid pending commands");
    try { await session.CommandAsync("-test-error"); throw new Exception("GDB error not raised"); }
    catch (GdbCommandException ex) { Check(ex.Response.Class == "error" && ex.Command == "-test-error", "GDB errors retain structured response"); }
    try { await session.CommandAsync("-test-never", timeout: TimeSpan.FromMilliseconds(100)); throw new Exception("Missing timeout"); }
    catch (TimeoutException) { passed.Add("unanswered command times out"); }
    using (var cancel = new CancellationTokenSource(100))
    {
        try { await session.CommandAsync("-test-never", cancel.Token); throw new Exception("Missing cancellation"); }
        catch (OperationCanceledException) { passed.Add("pending command cancellation works"); }
    }
    Check((await session.CommandAsync("-test-health")).GetString("value") == "healthy", "session survives command timeout and cancellation");
    try { await session.CommandAsync("-test-health\n-exec-continue"); throw new Exception("Newline injection accepted"); }
    catch (ArgumentException) { passed.Add("raw command newline injection rejected"); }
    try { await session.CommandAsync("-test-die"); throw new Exception("Process exit not reported"); }
    catch (EndOfStreamException) { passed.Add("process crash faults pending command"); }
}
await using (var session = new GdbSession())
{
    await session.StartAsync(FixtureOptions());
    try { await session.CommandAsync("-test-malformed"); throw new Exception("Protocol corruption not reported"); }
    catch (MiParseException) { passed.Add("protocol corruption fails pending request"); }
}
await using (var session = new GdbSession())
{
    await session.StartAsync(FixtureOptions());
    var pending = session.CommandAsync("-test-never");
    var firstDispose = session.DisposeAsync().AsTask();
    var secondDispose = session.DisposeAsync().AsTask();
    Check(ReferenceEquals(firstDispose, secondDispose), "concurrent session disposal shares one cleanup task");
    await Task.WhenAll(firstDispose, secondDispose);
    try { await pending; throw new Exception("Disposed command remained pending"); }
    catch (Exception ex) when (ex is EndOfStreamException or ObjectDisposedException or OperationCanceledException)
    { passed.Add("session disposal terminates pending commands"); }
    Check(!session.IsAlive && session.State == DebugState.Disposed, "disposed session remains safely inspectable");
}
await using (var session = new GdbSession())
{
    await session.StartAsync(FixtureOptions() with {
        SourceMappings = [new("/original", "C:/editor"), new("/build/.fxide-source", "C:/editor")],
        PreferredBreakpointSourceRoots = ["/build/.fxide-source"]
    });
    Check(session.GetBreakpointLocation("C:/editor/src/main.cpp", 31) == "/build/.fxide-source/src/main.cpp:31",
        "native breakpoint prefers compiled staging root over original-source alias");
}
var configDirectory = Path.Combine(Path.GetTempPath(), "fxstudio-core-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(configDirectory);
try
{
    var missingExecutable = Path.Combine(configDirectory, "missing-tool.exe");
    await using (var session = new GdbSession())
    {
        try { await session.StartAsync(FixtureOptions() with { ExecutablePath = missingExecutable }); throw new Exception("Missing GDB launched"); }
        catch (System.ComponentModel.Win32Exception) { }
        Check(!session.IsAlive && session.State == DebugState.Faulted, "missing GDB executable leaves safely disposable faulted session");
    }
    var sampleG1a = Path.Combine(configDirectory, "sample.g1a");
    await File.WriteAllBytesAsync(sampleG1a, fixtureG1a);
    await using (var session = new EmulatorSession())
    {
        try { await session.StartAsync(missingExecutable, sampleG1a, Path.Combine(configDirectory, "screen.bmp")); throw new Exception("Missing emulator launched"); }
        catch (System.ComponentModel.Win32Exception) { }
        Check(!session.IsAlive, "missing emulator executable leaves safely disposable session");
        await Task.WhenAll(session.DisposeAsync().AsTask(), session.DisposeAsync().AsTask());
        Check(!session.IsAlive, "concurrent emulator disposal is idempotent after launch failure");
    }
    var configFile = Path.Combine(configDirectory, "project.fxide.json");
    await new ProjectConfig { SourceDirectory = ".", BuildDirectory = "../build", Name = "Unicode 中文", NativeSdkDirectory = "../sdk", NativeWorkDirectory = "../cache" }.SaveAsync(configFile);
    var loaded = await ProjectConfig.LoadAsync(configFile);
    Check(loaded.Name == "Unicode 中文" && loaded.SourceDirectory == configDirectory, "project load resolves relative paths with Unicode");
    var movedDirectory = Path.Combine(configDirectory, "moved");
    Directory.CreateDirectory(movedDirectory);
    var movedConfig = Path.Combine(movedDirectory, "project.fxide.json");
    File.Copy(configFile, movedConfig);
    var moved = await ProjectConfig.LoadAsync(movedConfig);
    Check(moved.SourceDirectory == movedDirectory && moved.BuildDirectory == Path.Combine(configDirectory, "build"),
        "saved project configuration relocates without old machine paths");
    Check(moved.NativeSdkDirectory == Path.Combine(configDirectory, "sdk") && moved.NativeWorkDirectory == Path.Combine(configDirectory, "cache"),
        "project-specific native SDK and cache paths relocate relative to the project");
    var snapshotElf = Path.Combine(configDirectory, "source.elf");
    var snapshotG1a = Path.Combine(configDirectory, "source.g1a");
    await File.WriteAllBytesAsync(snapshotElf, fixtureElf);
    await File.WriteAllBytesAsync(snapshotG1a, fixtureG1a);
    var snapshotArtifact = new BuildArtifact {
        ElfPath = snapshotElf, G1APath = snapshotG1a, LinuxElfPath = "", LinuxG1APath = "",
        LinuxSourceDirectory = "", LinuxBuildDirectory = "", ManifestPath = "", Configuration = BuildConfiguration.Debug
    };
    var nativeImage = await NativeDebugImage.CreateAsync(snapshotArtifact, configDirectory);
    var frozenPath = nativeImage.DirectoryPath;
    var alteredOriginal = (byte[])fixtureG1a.Clone(); alteredOriginal[520] ^= 1;
    await File.WriteAllBytesAsync(snapshotG1a, alteredOriginal);
    Check((await nativeImage.Artifact.VerifyAsync()).IsMatch, "debug session freezes verified bytes against changes to original artifacts");
    Check(frozenPath.All(c => c < 128), "native GDB session uses an ASCII cache path");
    await nativeImage.DisposeAsync(); await nativeImage.DisposeAsync();
    Check(!Directory.Exists(frozenPath) && File.Exists(snapshotElf) && File.Exists(snapshotG1a), "debug image disposal removes its own files and preserves originals");
}
finally { Directory.Delete(configDirectory, recursive: true); }
Console.WriteLine($"PASS: {passed.Count} checks");
foreach (var name in passed) Console.WriteLine("  " + name);

static async Task RunFixtureAsync()
{
    Console.InputEncoding = Encoding.UTF8;
    Console.OutputEncoding = new UTF8Encoding(false);
    var held = new Dictionary<string, string>();
    while (await Console.In.ReadLineAsync() is { } line)
    {
        var tokenEnd = 0;
        while (tokenEnd < line.Length && char.IsAsciiDigit(line[tokenEnd])) tokenEnd++;
        var token = line[..tokenEnd];
        var command = line[tokenEnd..];
        if (command == "-gdb-exit") { Console.WriteLine(token + "^exit"); return; }
        if (command == "-test-die") { Environment.Exit(3); return; }
        if (command == "-test-malformed") { Console.WriteLine(token + "^done,bad={"); continue; }
        if (command == "-test-never") continue;
        if (command == "-test-error") { Console.WriteLine(token + "^error,msg=\"Test rejection\""); continue; }
        if (command == "-test-health") { Console.WriteLine(token + "^done,value=\"healthy\""); continue; }
        if (command.StartsWith("-test-order-"))
        {
            held[command[12..]] = token;
            if (held.Count < 3) continue;
            Console.WriteLine("*running,thread-id=\"all\"");
            Console.WriteLine(held["three"] + "^done,value=\"three\"");
            Console.WriteLine("*stopped,reason=\"breakpoint-hit\",frame={level=\"0\",fullname=\"/staging/main.cpp\",line=\"9\"}");
            Console.WriteLine(held["one"] + "^done,value=\"one\"");
            Console.WriteLine(held["two"] + "^done,value=\"two\"");
            continue;
        }
        if (command.StartsWith("-target-select"))
        {
            Console.WriteLine("=thread-group-started,id=\"i1\",pid=\"1\"");
            Console.WriteLine(token + "^connected");
            Console.WriteLine("*stopped,frame={level=\"0\",addr=\"0x00300200\",func=\"main\",fullname=\"/staging/deep/main.cpp\",line=\"3\"}");
            continue;
        }
        Console.WriteLine(token + "^done");
    }
}

static (byte[] elf, byte[] g1a) CreateArtifactFixture()
{
    var elf = new byte[0x130];
    elf[0] = 0x7f; elf[1] = (byte)'E'; elf[2] = (byte)'L'; elf[3] = (byte)'F'; elf[4] = 1; elf[5] = 2; elf[6] = 1;
    void U16(int offset, ushort value) => BinaryPrimitives.WriteUInt16BigEndian(elf.AsSpan(offset, 2), value);
    void U32(int offset, uint value) => BinaryPrimitives.WriteUInt32BigEndian(elf.AsSpan(offset, 4), value);
    U16(16, 2); U16(18, 42); U32(20, 1); U32(24, ArtifactPairVerifier.RomBase); U32(28, 52); U16(40, 52); U16(42, 32); U16(44, 3);
    void Segment(int index, uint fileOffset, uint vma, uint lma, uint size, uint memory)
    {
        var offset = 52 + 32 * index;
        U32(offset, 1); U32(offset + 4, fileOffset); U32(offset + 8, vma); U32(offset + 12, lma);
        U32(offset + 16, size); U32(offset + 20, memory); U32(offset + 24, 7); U32(offset + 28, 1);
    }
    Segment(0, 0x100, 0x00300200, 0x00300200, 32, 32);
    Segment(1, 0x120, 0x08100000, 0x00300230, 16, 16);
    Segment(2, 0x130, 0x08100010, 0, 0, 256);
    for (var i = 0; i < 48; i++) elf[0x100 + i] = (byte)(i + 1);
    var g1a = new byte[512 + 64];
    elf.AsSpan(0x100, 32).CopyTo(g1a.AsSpan(512));
    elf.AsSpan(0x120, 16).CopyTo(g1a.AsSpan(560));
    WriteG1AHeader(g1a);
    return (elf, g1a);
}

static void WriteG1AHeader(byte[] g1a)
{
    var header = new byte[32];
    "USBPower"u8.CopyTo(header); header[8] = 0xf3; header[10] = 0x10; header[12] = 0x10; header[15] = 1;
    BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(16, 4), (uint)g1a.Length);
    header[14] = (byte)(g1a.Length + 0x41); header[20] = (byte)(g1a.Length + 0xb8);
    var checksum = 0;
    for (var i = 0x300; i < 0x310; i += 2)
        checksum = (checksum + (i < g1a.Length ? g1a[i] << 8 : 0) + (i + 1 < g1a.Length ? g1a[i + 1] : 0)) & 0xffff;
    BinaryPrimitives.WriteUInt16BigEndian(header.AsSpan(22, 2), (ushort)checksum);
    for (var i = 0; i < 32; i++) g1a[i] = (byte)~header[i];
    BinaryPrimitives.WriteUInt32BigEndian(g1a.AsSpan(0x1f0, 4), (uint)g1a.Length);
}

static async Task RunIntegrationAsync(string[] arguments)
{
    if (arguments.Length != 6)
        throw new ArgumentException("--integration EMULATOR GDB ELF G1A WORKDIR");
    var work = Path.GetFullPath(arguments[5]);
    Directory.CreateDirectory(work);
    var framebuffer = Path.Combine(work, "screen.bmp");
    if (File.Exists(framebuffer)) File.Delete(framebuffer);
    await using var emulator = new EmulatorSession();
    await using var debugger = new GdbSession();
    emulator.Output += x => Console.WriteLine("EMU " + x);
    debugger.Output += x => Console.Write("GDB " + x);
    await emulator.StartAsync(arguments[1], arguments[4], framebuffer);
    await debugger.StartAsync(arguments[2], arguments[3], emulator.GdbPort);
    var initialFrame = File.Exists(framebuffer) ? await File.ReadAllBytesAsync(framebuffer) : [];
    var breakpoint = await debugger.InsertBreakpointAsync("main");
    var stop = new TaskCompletionSource<MiRecord>(TaskCreationOptions.RunContinuationsAsynchronously);
    debugger.Stopped += r => stop.TrySetResult(r);
    await debugger.ContinueAsync();
    var record = await stop.Task.WaitAsync(TimeSpan.FromSeconds(30));
    if (record.GetString("reason") != "breakpoint-hit") throw new Exception("Expected main breakpoint.");
    Console.WriteLine("Main stopped: " + debugger.GetStoppedFrame());
    foreach (var local in await debugger.GetLocalsAsync()) Console.WriteLine("LOCAL " + local);
    foreach (var frame in await debugger.GetStackAsync()) Console.WriteLine("FRAME " + frame);
    Console.WriteLine("Registers: " + (await debugger.GetRegistersAsync()).Count);
    Console.WriteLine("Memory: " + Convert.ToHexString(await debugger.ReadMemoryAsync("$pc", 16)));
    foreach (var instruction in await debugger.GetDisassemblyAsync("$pc", "$pc+32")) Console.WriteLine("ASM " + instruction);
    await debugger.DeleteBreakpointAsync(breakpoint.Number);
    Console.WriteLine("INTEGRATION PASS: SuperH G1A main breakpoint, variables, stack, registers, memory, disassembly");
    if (arguments[0] == "--source-cas01")
    {
        async Task<MiRecord> StopAfter(Func<Task<MiRecord>> operation)
        {
            var next = new TaskCompletionSource<MiRecord>(TaskCreationOptions.RunContinuationsAsynchronously);
            void Handler(MiRecord r) => next.TrySetResult(r);
            debugger.Stopped += Handler;
            try { await operation(); return await next.Task.WaitAsync(TimeSpan.FromSeconds(20)); }
            finally { debugger.Stopped -= Handler; }
        }
        await StopAfter(() => debugger.NextAsync());
        if (debugger.GetStoppedFrame()?.Function != "main" || debugger.GetStoppedFrame()?.Line == 62)
            throw new Exception("Source next did not move to another main line.");
        var drawBreakpoint = await debugger.InsertBreakpointAsync("ui_draw");
        await StopAfter(() => debugger.ContinueAsync());
        var drawFrame = debugger.GetStoppedFrame();
        if (drawFrame?.Function != "ui_draw" || drawFrame.Line != 766) throw new Exception("Expected paired CAS01 ui_draw source breakpoint.");
        var stack = await debugger.GetStackAsync();
        if (stack.Count < 2 || stack[0].Function != "ui_draw" || stack[1].Function != "main")
            throw new Exception("Source call stack did not contain ui_draw -> main.");
        var notice = await debugger.EvaluateAsync("ui->notice");
        if (!notice.Contains("Starting CAS", StringComparison.Ordinal)) throw new Exception("Typed pointer expression did not match actual target state.");
        Console.WriteLine("SOURCE_VALUE " + notice);
        Console.WriteLine("SOURCE_STACK " + string.Join(" -> ", stack.Select(f => f.Function)));
        var variable = await debugger.CreateVariableObjectAsync("*ui");
        var children = await debugger.GetVariableChildrenAsync(variable.ObjectName!);
        if (!children.Any(c => c.Name == "notice")) throw new Exception("Structured variable children missing notice field.");
        await debugger.DeleteVariableObjectAsync(variable.ObjectName!);
        await debugger.DeleteBreakpointAsync(drawBreakpoint.Number);
        await StopAfter(() => debugger.NextAsync());
        var nextLine = debugger.GetStoppedFrame()?.Line;
        if (nextLine == 766) throw new Exception("Source next did not progress.");
        await StopAfter(() => debugger.StepAsync());
        if (debugger.State != DebugState.Stopped) throw new Exception("Source step did not stop.");
        await StopAfter(() => debugger.FinishAsync());
        if (debugger.GetStoppedFrame()?.Function != "main") throw new Exception("Source finish did not return to caller.");
        if (!File.Exists(framebuffer)) throw new Exception("No new framebuffer after executing ui_draw.");
        if ((await File.ReadAllBytesAsync(framebuffer)).SequenceEqual(initialFrame))
            throw new Exception("Framebuffer remained unchanged after executing ui_draw.");
        Console.WriteLine("SOURCE PASS: actual CAS01 ELF/G1A, next/step/finish, source lines, ui_draw->main stack, typed pointer value, structured children, changed paused framebuffer");
    }
}

static async Task RunTransportAsync(string[] arguments)
{
    if (arguments.Length != 5) throw new ArgumentException("--transport EMULATOR GDB G1A WORKDIR");
    var work = Path.GetFullPath(arguments[4]);
    Directory.CreateDirectory(work);
    var framebuffer = Path.Combine(work, "screen.bmp");
    if (File.Exists(framebuffer)) File.Delete(framebuffer);
    await using var emulator = new EmulatorSession();
    await using var debugger = new GdbSession();
    emulator.Output += x => Console.WriteLine("EMU " + x);
    debugger.Output += x => Console.Write("GDB " + x);
    await emulator.StartAsync(arguments[1], arguments[3], framebuffer);
    await debugger.StartAsync(arguments[2], "", emulator.GdbPort);
    Console.WriteLine("REGISTERS " + (await debugger.GetRegistersAsync()).Count);
    Console.WriteLine("ENTRY_MEMORY " + Convert.ToHexString(await debugger.ReadMemoryAsync("$pc", 16)));
    foreach (var instruction in await debugger.GetDisassemblyAsync("$pc", "$pc+16")) Console.WriteLine("ASM " + instruction);
    var r4 = await debugger.EvaluateAsync("$r4");
    await debugger.WriteRegisterAsync(4, "0x1234");
    if (await debugger.EvaluateAsync("$r4") != "4660") throw new Exception("Register write did not reach the target.");
    await debugger.WriteRegisterAsync(4, r4);
    var saved = await debugger.ReadMemoryAsync("$sp-16", 4);
    await debugger.WriteMemoryAsync("$sp-16", new byte[] { 0x12, 0x34, 0x56, 0x78 });
    if (! (await debugger.ReadMemoryAsync("$sp-16", 4)).SequenceEqual(new byte[] { 0x12, 0x34, 0x56, 0x78 }))
        throw new Exception("Memory write did not reach the target.");
    await debugger.WriteMemoryAsync("$sp-16", saved);
    var variable = await debugger.CreateVariableObjectAsync("$r4");
    if (variable.ObjectName is null) throw new Exception("Variable object missing.");
    await debugger.DeleteVariableObjectAsync(variable.ObjectName);
    var bp = await debugger.InsertBreakpointAsync("*0x00300202", "$pc == 0x00300202");
    async Task<MiRecord> StopAfter(Func<Task<MiRecord>> operation)
    {
        var next = new TaskCompletionSource<MiRecord>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Handler(MiRecord r) => next.TrySetResult(r);
        debugger.Stopped += Handler;
        try { await operation(); return await next.Task.WaitAsync(TimeSpan.FromSeconds(15)); }
        finally { debugger.Stopped -= Handler; }
    }
    var breakpointStop = await StopAfter(() => debugger.ContinueAsync());
    if (breakpointStop.GetString("reason") != "breakpoint-hit" || await debugger.EvaluateAsync("$pc") != "0x300202")
        throw new Exception("Conditional instruction breakpoint did not stop at the expected address.");
    await debugger.DeleteBreakpointAsync(bp.Number);
    await StopAfter(() => debugger.StepInstructionAsync());
    if (await debugger.EvaluateAsync("$pc") != "0x300204") throw new Exception("Instruction step did not advance exactly one instruction.");
    var watchAddress = await debugger.EvaluateAsync("(unsigned int)($sp-4)");
    var watchpoint = await debugger.InsertWatchpointAsync("*(unsigned int*)" + watchAddress);
    if (!(await debugger.GetBreakpointsAsync()).Any(x => x.Number == watchpoint.Number))
        throw new Exception("Created watchpoint was not listed.");
    var watchStop = await StopAfter(() => debugger.ContinueAsync());
    if (watchStop.GetString("reason") != "watchpoint-trigger") throw new Exception("Actual CPU stack write did not trigger watchpoint.");
    await debugger.DeleteBreakpointAsync(watchpoint.Number);
    Console.WriteLine("REGISTER_WRITE MEMORY_WRITE VARIABLE_OBJECT CONDITIONAL_BREAKPOINT STEPI HARDWARE_WATCHPOINT PASS");
    await debugger.ContinueAsync();
    await Task.Delay(1000);
    await emulator.SendKeyAsync("2", true);
    await Task.Delay(150);
    await emulator.SendKeyAsync("2", false);
    await Task.Delay(150);
    var stopped = new TaskCompletionSource<MiRecord>(TaskCreationOptions.RunContinuationsAsynchronously);
    debugger.Stopped += record => stopped.TrySetResult(record);
    await debugger.PauseAsync();
    await stopped.Task.WaitAsync(TimeSpan.FromSeconds(10));
    Console.WriteLine("STATUS " + await emulator.StatusAsync());
    if (!File.Exists(emulator.FramebufferPath)) throw new Exception("No framebuffer from actual binary.");
    Console.WriteLine("TRANSPORT PASS: real G1A, register/memory read-write, variable object, conditional instruction breakpoint, stepi, hardware write-watchpoint, disassembly, run, key, interrupt, framebuffer");
}
