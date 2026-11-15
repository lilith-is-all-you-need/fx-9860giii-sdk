using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using FxStudio.Automation;

internal static class Program
{
    private static int _checks;
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNamingPolicy=JsonNamingPolicy.CamelCase };
    private static JsonElement J(object value) => JsonSerializer.SerializeToElement(value,JsonOptions);
    private static JsonElement Raw(string value) => JsonDocument.Parse(value).RootElement.Clone();
    private static void Check(bool value,string name) { if(!value)throw new Exception("FAIL: "+name); Interlocked.Increment(ref _checks); }
    private static async Task Error(string code,Func<Task<object?>> action,string name)
    {
        try { await action(); throw new Exception("FAIL: "+name+" did not throw "+code); }
        catch(AutomationException ex) { Check(ex.Code==code,name+" expected "+code+", received "+ex.Code+": "+ex.Message); }
    }
    public static async Task Main(string[] args)
    {
        var root=Path.Combine(Path.GetTempPath(),"FxStudio-automation-tests-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try {
            await Contracts(root);
            if(args.Length>0) {
                if(args.Length!=3 || args[0]!="--integration")throw new ArgumentException("Usage: [--integration PACKAGE_ROOT COUNTER_CPP_PROJECT]");
                await Integration(root,Path.GetFullPath(args[1]),Path.GetFullPath(args[2]));
            }
            Console.WriteLine($"PASS {_checks} automation checks"+(args.Length==0?" (contract/state; native integration not requested)":" including real native build and SuperH debugging"));
        } finally {
            // The test directory is newly allocated above. Do not follow reparse points during cleanup.
            DeleteOwnTree(root);
        }
    }
    private static async Task Contracts(string root)
    {
        var project=Path.Combine(root,"中文's project"); Directory.CreateDirectory(project);
        await File.WriteAllTextAsync(Path.Combine(project,"CMakeLists.txt"),"cmake_minimum_required(VERSION 3.20)\nproject(contract NONE)\n");
        await using var service=new AutomationService(Path.Combine(root,"missing-package"),Path.Combine(root,"data"));
        var commands=service.Commands;
        Check(commands.Count==23,"23 implemented commands");
        Check(commands.Select(x=>(x.Name,x.Version)).Distinct().Count()==commands.Count,"unique command versions");
        foreach(var definition in commands) {
            var schema=(JsonElement)definition.InputSchema;
            Check(definition.Version==1 && schema.GetProperty("additionalProperties").ValueKind==JsonValueKind.False,"strict schema "+definition.Name);
        }
        Check(commands.Single(x=>x.Name=="debug.snapshot").Effect=="read","snapshot is read");
        Check(commands.Single(x=>x.Name=="debug.variable.children").Effect=="read","children is read");
        Check(commands.Single(x=>x.Name=="debug.evaluate").Effect=="mutate","general evaluation mutates");
        var diagnostic=AutomationService.ParseDiagnostic(@"C:\中文's project\src\main.cpp:42:17: error: expected ';'");
        Check(diagnostic is {File:@"C:\中文's project\src\main.cpp",Line:42,Column:17,Severity:"error"},"GCC Windows diagnostic line and column");
        Check(AutomationService.ParseDiagnostic("src/main.cpp:4:2: warning: example") is {File:"src/main.cpp",Line:4,Column:2},"GCC relative diagnostic line and column");
        Check(AutomationService.ParseDiagnostic("/tmp/src/main.c:90: note: example") is {File:"/tmp/src/main.c",Line:90,Column:null},"GCC diagnostic without column");
        Check(AutomationService.ParseDiagnostic("Building 1 of 4") is null,"ordinary logs are not diagnostics");
        await Error("UNKNOWN_COMMAND",()=>service.ExecuteAsync("not-a-command",J(new{})),"unknown command");
        await Error("UNSUPPORTED_VERSION",()=>service.ExecuteAsync("session.list",2,J(new{})),"unsupported version");
        Check(J((await service.ExecuteAsync("session.list",1,J(new{})))!).GetProperty("sessions").GetArrayLength()==0,"explicit v1 dispatch");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.list",J(new { extra=true })),"unknown argument");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.open",Raw("{\"projectPath\":\"a\",\"projectPath\":\"b\"}")),"duplicate argument");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.open",J(new{})),"missing required argument");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.open",J(new {projectPath=" "})),"blank path");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.open",J(new {projectPath="a\0b"})),"NUL path");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("session.list",Raw("[]")),"object required");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("build.run",J(new {sessionId="missing",configuration="Other"})),"configuration enum");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.memory.read",J(new {sessionId="missing",address="0",count=65537})),"memory count upper bound");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.memory.read",J(new {sessionId="missing",address="0",count=0})),"memory count lower bound");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.memory.read",J(new {sessionId="missing",address="0",count="8"})),"memory count integer required");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.key",J(new {sessionId="missing",key="PLUS",action="press",durationMs=2001})),"key duration limit");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.key",J(new {sessionId="missing",key="plus",action="press"})),"canonical key required");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.snapshot",J(new {sessionId="missing",expressions=Enumerable.Repeat("x",33).ToArray()})),"expression count limit");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.breakpoint.set",J(new {sessionId="missing",location="main",line=1})),"breakpoint exclusive location");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.breakpoint.set",J(new {sessionId="missing",file="main.c"})),"breakpoint missing line");
        await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.breakpoint.remove",J(new {sessionId="missing",number="1 -exec-continue"})),"breakpoint number injection rejected");
        foreach(var hex in new[]{"F","GG"," ",new string('A',131074)})
            await Error("INVALID_ARGUMENT",()=>service.ExecuteAsync("debug.memory.write",J(new {sessionId="missing",address="0",hex})),"invalid hex bytes");
        foreach(var expression in new[]{"foo()","x=3","++x","x++","x+1","x[1+2]","x[-1]","x[foo()]","x;continue","x\n","(x)","*x","x::y","x.*y"}) {
            await Error("INVALID_EXPRESSION",()=>service.ExecuteAsync("debug.snapshot",J(new {sessionId="missing",expressions=new[]{"good",expression}})),"snapshot validates all paths before lookup: "+expression);
            await Error("INVALID_EXPRESSION",()=>service.ExecuteAsync("debug.variable.children",J(new {sessionId="missing",expression})),"children rejects effects: "+expression);
        }
        foreach(var expression in new[]{"counter","counter.value","ptr->child[0].value","$pc","array[123][0]"}) {
            await Error("SESSION_NOT_FOUND",()=>service.ExecuteAsync("debug.snapshot",J(new {sessionId="missing",expressions=new[]{expression}})),"snapshot allows safe path: "+expression);
            await Error("SESSION_NOT_FOUND",()=>service.ExecuteAsync("debug.variable.children",J(new {sessionId="missing",expression})),"children allows safe path: "+expression);
        }
        foreach(var address in new[]{"foo()","x=2","$pc+4+4","$pc+foo","&x[3-1]","0x10;continue","$pc\n"}) {
            await Error("INVALID_EXPRESSION",()=>service.ExecuteAsync("debug.memory.read",J(new {sessionId="missing",address,count=8})),"memory read rejects effects: "+address);
            await Error("INVALID_EXPRESSION",()=>service.ExecuteAsync("debug.disassemble",J(new {sessionId="missing",start="0",end=address})),"disassembly rejects effects: "+address);
        }
        foreach(var address in new[]{"0x00300200","1234","$pc","&counter.value","$pc + 0x10","&array[0]-4"})
            await Error("SESSION_NOT_FOUND",()=>service.ExecuteAsync("debug.memory.read",J(new {sessionId="missing",address,count=1})),"memory safe address: "+address);
        await Error("SESSION_NOT_FOUND",()=>service.ExecuteAsync("debug.evaluate",J(new {sessionId="missing",expression="x=3"})),"arbitrary evaluate remains supported");

        var sessions=new List<SessionInfo>();
        var events=new List<AutomationEvent>();
        service.Event+=_=>throw new Exception("Subscriber faults must not break operations");
        service.Event+=events.Add;
        for(var i=0;i<8;i++)sessions.Add((SessionInfo)(await service.ExecuteAsync("session.open",J(new {projectPath=i==1?Path.Combine(project,"CMakeLists.txt"):project})))!);
        Check(sessions.All(s=>s.State=="Open" && s.Revision==1 && s.Artifact is null),"initial states");
        Check(sessions.All(s=>s.SourceDirectory==project),"Unicode/apostrophe source path preserved");
        Check(!File.Exists(Path.Combine(project,"project.fxide.json")),"opening does not write config");
        Check(events.Count(x=>x.Kind=="session.opened")==8,"subscriber fault isolation");
        await Error("SESSION_LIMIT",()=>service.ExecuteAsync("session.open",J(new {projectPath=project})),"session limit");
        var id=sessions[0].SessionId;
        await Error("SDK_MISSING",()=>service.ExecuteAsync("build.run",J(new {sessionId=id})),"missing SDK explicit");
        await Error("BUILD_REQUIRED",()=>service.ExecuteAsync("debug.launch",J(new {sessionId=id})),"launch needs successful build");
        await Error("NO_DEBUG_SESSION",()=>service.ExecuteAsync("debug.snapshot",J(new {sessionId=id})),"snapshot no debugger");
        await Error("NO_DEBUG_SESSION",()=>service.ExecuteAsync("debug.resume",J(new {sessionId=id})),"resume no debugger");
        Check(((SessionInfo)(await service.ExecuteAsync("debug.stop",J(new {sessionId=id})))!).State=="Open","stop is idempotent");
        var inspect=J((await service.ExecuteAsync("project.inspect",J(new {sessionId=id})))!);
        Check(inspect.GetProperty("backend").GetString()=="native" && inspect.GetProperty("missingSdkFiles").GetArrayLength()>0,"inspect available without SDK");
        await service.ExecuteAsync("session.close",J(new {sessionId=id}));
        await Error("SESSION_NOT_FOUND",()=>service.ExecuteAsync("project.inspect",J(new {sessionId=id})),"closed session rejected");
        var config=Path.Combine(project,"custom.fxide.json");
        var configText="{\"name\":\"Configured\",\"sourceDirectory\":\".\",\"buildDirectory\":\"out\",\"backend\":\"wsl\"}";
        await File.WriteAllTextAsync(config,configText);
        var configured=(SessionInfo)(await service.ExecuteAsync("session.open",J(new {projectPath=config,sdkPath=root})))!;
        Check(configured.Name=="Configured" && configured.BuildDirectory==Path.Combine(project,"out") && configured.SdkPath==root,"relative config and SDK override");
        Check(await File.ReadAllTextAsync(config)==configText,"native override never rewrites config");
        await service.DisposeAsync();
        await service.DisposeAsync();
        await Error("SERVICE_CLOSED",()=>service.ExecuteAsync("session.list",J(new{})),"disposed service rejects commands");
    }

    private static async Task Integration(string root,string package,string example)
    {
        var project=Path.Combine(root,"real 中文's counter");
        CopyProject(example,project);
        var events=new ConcurrentQueue<AutomationEvent>();
        await using var service=new AutomationService(package,Path.Combine(root,"debug-images"));
        service.Event+=events.Enqueue;
        var opened=(SessionInfo)(await service.ExecuteAsync("session.open",J(new{projectPath=project})))!;
        var id=opened.SessionId;
        Task<object?> Call(string command,object? extra=null) {
            var args=extra is null?new Dictionary<string,object?>():JsonSerializer.Deserialize<Dictionary<string,object?>>(JsonSerializer.Serialize(extra,JsonOptions))!;
            args["sessionId"]=id; return service.ExecuteAsync(command,J(args));
        }
        Console.WriteLine("Building real C++ example with bundled native SDK...");
        var building=Call("build.run",new{configuration="Debug"});
        await Error("BUSY",()=>Call("project.inspect"),"real build serializes session");
        await Error("BUSY",()=>Call("session.close"),"close never races active build");
        var built=J((await building)!);
        Check(File.Exists(built.GetProperty("artifact").GetProperty("elfPath").GetString()),"real ELF output");
        Check(events.Any(e=>e.Kind=="build.log") && events.Any(e=>e.Kind=="build.completed"),"real build events");
        var idle=J((await Call("project.inspect"))!).GetProperty("session");
        Check(idle.GetProperty("state").GetString()=="Open" && idle.GetProperty("revision").GetInt64()==built.GetProperty("revision").GetInt64(),"build result revision is final");
        var stopped=(SessionInfo)(await Call("debug.launch"))!;
        Check(stopped.State=="Stopped" && stopped.LastStop?.Frame?.Function=="main","real launch stops in main");
        await Error("DEBUG_ACTIVE",()=>Call("build.run"),"build rejected during debugger");
        await Error("NOT_RUNNING",()=>Call("debug.pause"),"pause requires running");
        await Error("NOT_RUNNING",()=>Call("debug.key",new{key="PLUS",action="press"}),"keypress requires running");
        var first=(SnapshotInfo)(await Call("debug.snapshot",new{expressions=new[]{"counter.value"}}))!;
        Check(first.Consistent && first.Frames?.First().Function=="main" && first.Expressions![0].Value=="0","real stopped snapshot");
        Check(first.Registers is not null && first.Errors.Count==0,"real snapshot sections succeed");
        Check(first.TargetStatus?.GetProperty("state").GetString()=="paused","paused snapshot contains actual emulator status");
        Check(first.Screen is {Width:128,Height:64},"real framebuffer dimensions");
        await Error("GDB_ERROR",()=>Call("debug.evaluate",new{expression="clamp_counter(2)"}),"inferior function calls are disabled");
        var afterRejectedCall=(SnapshotInfo)(await Call("debug.snapshot",new{include=Array.Empty<string>(),expressions=new[]{"counter.value"}}))!;
        Check(afterRejectedCall.Expressions![0].Value=="0","rejected function call leaves target unchanged");
        Check(!JsonSerializer.Serialize(first,JsonOptions).Contains("\"raw\"",StringComparison.OrdinalIgnoreCase),"public snapshot omits MI raw objects");
        var children=J((await Call("debug.variable.children",new{expression="counter"}))!);
        Check(children.GetProperty("children").GetArrayLength()==3,"real struct children: "+children.GetRawText());
        var memory=J((await Call("debug.memory.read",new{address="&counter.value",count=4}))!);
        Check(memory.GetProperty("hex").GetString()=="00000000","real memory contents");
        var instructions=J((await Call("debug.disassemble",new{start="$pc",end="$pc+16"}))!);
        Check(instructions.GetProperty("instructions").GetArrayLength()>0,"real disassembly");
        await Call("debug.evaluate",new{expression="counter.value=7"});
        var changed=(SnapshotInfo)(await Call("debug.snapshot",new{include=Array.Empty<string>(),expressions=new[]{"counter.value"}}))!;
        Check(changed.Expressions![0].Value=="7" && changed.Revision>first.Revision,"evaluation writes actual target with revision");
        await Call("debug.memory.write",new{address="&counter.value",hex="00 00 00 00"});
        await Call("debug.resume");
        await Error("NOT_STOPPED",()=>Call("debug.variable.children",new{expression="counter"}),"running inspection rejected");
        await Task.Delay(1200);
        var running=(SnapshotInfo)(await Call("debug.snapshot",new{expressions=new[]{"counter.value"}}))!;
        Check(!running.Consistent && running.State=="Running" && running.Frames is null && running.Locals is null && running.Registers is null,"running snapshot does not pause or inspect target");
        Check(running.Errors.Any(e=>e.Code=="NOT_STOPPED") && running.Screen is not null,"running snapshot gives real screen and section errors");
        Check(running.TargetStatus?.GetProperty("state").GetString()=="running" && running.TargetStatus?.GetProperty("cycles").GetUInt64()>0,"running snapshot reports actual PC/cycles/state");
        var beforeScreen=running.Screen!;
        await Call("debug.key",new{key="PLUS",action="press"});
        await Task.Delay(180);
        await Call("debug.pause");
        var after=(SnapshotInfo)(await Call("debug.snapshot",new{expressions=new[]{"counter.value"}}))!;
        Check(after.Consistent && int.Parse(after.Expressions![0].Value!)>0,"calculator key changes compiled SuperH program");
        Check(after.Screen!.Sha256!=beforeScreen.Sha256,"key updates actual framebuffer");
        Check(Convert.ToHexStringLower(SHA256.HashData(Convert.FromBase64String(after.Screen.Base64Bmp)))==after.Screen.Sha256,"screen hash covers snapshot bytes");
        var step=(SessionInfo)(await Call("debug.step",new{mode="instruction"}))!;
        Check(step.State=="Stopped" && step.LastStop is not null,"instruction step waits actual stop");
        var bp=(BreakpointInfo)(await Call("debug.breakpoint.set",new{location="change_counter",condition="delta==1"}))!;
        Check(bp.Number.Length>0,"real conditional breakpoint");
        await Call("debug.breakpoint.enabled",new{number=bp.Number,enabled=false});
        await Call("debug.breakpoint.remove",new{number=bp.Number});
        await Call("debug.stop");
        Check(!Directory.Exists(Path.GetDirectoryName(after.Screen.Path)),"stop removes frozen session image");

        // A real compiler failure must clear the previous successful artifact and expose diagnostics.
        var source=Path.Combine(project,"src","main.cpp");
        var original=await File.ReadAllTextAsync(source);
        await File.AppendAllTextAsync(source,"\n#error automation_expected_compile_failure\n");
        await Error("BUILD_FAILED",()=>Call("build.run"),"real compiler failure");
        Check(events.Any(e=>e.Kind=="build.diagnostic"),"structured GCC diagnostic event");
        await Error("BUILD_REQUIRED",()=>Call("debug.launch"),"failed build cannot launch stale artifact");
        await File.WriteAllTextAsync(source,original);

        // CMake performs a real long-running configure step; cancellation must terminate it and release the gate.
        var cmake=Path.Combine(project,"CMakeLists.txt");
        var cmakeOriginal=await File.ReadAllTextAsync(cmake);
        await File.WriteAllTextAsync(cmake,cmakeOriginal+"\nexecute_process(COMMAND \"${CMAKE_COMMAND}\" -E sleep 30)\n");
        using(var cancellation=new CancellationTokenSource()) {
            var cancelBuild=service.ExecuteAsync("build.run",J(new{sessionId=id}),cancellation.Token);
            await Task.Delay(300); cancellation.Cancel();
            try { await cancelBuild.WaitAsync(TimeSpan.FromSeconds(20)); throw new Exception("Expected cancelled build"); }
            catch(OperationCanceledException) { Check(true,"real build cancellation"); }
        }
        Check(J((await Call("project.inspect"))!).GetProperty("session").GetProperty("state").GetString()=="Open","cancel releases gate and state");
        await Call("session.close");
        Check(J((await service.ExecuteAsync("session.list",J(new{})))!).GetProperty("sessions").GetArrayLength()==0,"close clears live session");
        Console.WriteLine("Real native build/debug/error/cancellation integration passed.");
    }
    private static void CopyProject(string source,string destination)
    {
        Directory.CreateDirectory(destination);
        foreach(var file in Directory.EnumerateFiles(source))if(Path.GetFileName(file)!="project.fxide.json")File.Copy(file,Path.Combine(destination,Path.GetFileName(file)));
        foreach(var directory in Directory.EnumerateDirectories(source)) {
            var name=Path.GetFileName(directory);
            if(name==".fxstudio" || name.StartsWith("build",StringComparison.OrdinalIgnoreCase))continue;
            if((File.GetAttributes(directory)&FileAttributes.ReparsePoint)!=0)continue;
            CopyProject(directory,Path.Combine(destination,name));
        }
    }
    private static void DeleteOwnTree(string directory)
    {
        if(!Directory.Exists(directory))return;
        foreach(var entry in Directory.EnumerateFileSystemEntries(directory)) {
            var attributes=File.GetAttributes(entry);
            if((attributes&FileAttributes.ReparsePoint)!=0)continue;
            if((attributes&FileAttributes.Directory)!=0)DeleteOwnTree(entry);
            else { File.SetAttributes(entry,attributes&~FileAttributes.ReadOnly); File.Delete(entry); }
        }
        Directory.Delete(directory);
    }
}
