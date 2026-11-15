using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using FxStudio.Core;

namespace FxStudio.Automation;

public sealed partial class AutomationService
{
    internal const string VariablePathPattern = @"(?:[A-Za-z_][A-Za-z0-9_]*|\$[A-Za-z_][A-Za-z0-9_]*)(?:(?:\.|->)[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*";
    internal const string AddressPattern = @"(?:0[xX][0-9A-Fa-f]+|[0-9]+|&?"+VariablePathPattern+@")(?:\s*[+-]\s*(?:0[xX][0-9A-Fa-f]+|[0-9]+))?";
    private static void ValidateSemantics(string command,JsonElement args)
    {
        static void PathExpression(string text) { if(!Regex.IsMatch(text,"\\A"+VariablePathPattern+"\\z",RegexOptions.CultureInvariant)) throw new AutomationException("INVALID_EXPRESSION","Only a variable/register path with .field, ->field or [nonnegative constant] is permitted; use debug.evaluate for general expressions."); }
        if(command=="debug.snapshot" && args.TryGetProperty("expressions",out var expressions)) foreach(var item in expressions.EnumerateArray()) PathExpression(item.GetString()!);
        if(command=="debug.variable.children") PathExpression(Text(args,"expression"));
        if(command is "debug.memory.read" or "debug.disassemble") {
            foreach(var field in command=="debug.memory.read"?new[]{"address"}:new[]{"start","end"})
                if(!Regex.IsMatch(Text(args,field),"\\A"+AddressPattern+"\\z",RegexOptions.CultureInvariant))
                    throw new AutomationException("INVALID_EXPRESSION","Read addresses must be a numeric address or variable/register path, optionally with + or - constant offsets.");
        }
        if(command=="debug.memory.write") {
            var hex=string.Concat(Text(args,"hex").Where(c=>!char.IsWhiteSpace(c)));
            if(hex.Length is <2 or >131072 || hex.Length%2!=0 || !hex.All(Uri.IsHexDigit)) throw new AutomationException("INVALID_ARGUMENT","Hex must contain 1–65536 complete bytes.");
        }
        if(command=="debug.key" && !Regex.IsMatch(Text(args,"key"),@"\A[A-Z0-9_]+\z",RegexOptions.CultureInvariant)) throw new AutomationException("INVALID_ARGUMENT","Use a canonical uppercase calculator key name.");
    }

    private async Task<SnapshotInfo> SnapshotAsync(Session s,JsonElement args,CancellationToken ct)
    {
        var gdb=s.Gdb ?? throw new AutomationException("NO_DEBUG_SESSION","Launch the debugger before requesting a debug snapshot.");
        var requested=args.TryGetProperty("include",out var included)?included.EnumerateArray().Select(x=>x.GetString()!).ToHashSet(StringComparer.Ordinal):new HashSet<string>(["stack","locals","registers","breakpoints","screen"],StringComparer.Ordinal);
        var expressions=args.TryGetProperty("expressions",out var expressionArray)?expressionArray.EnumerateArray().Select(x=>x.GetString()!).ToArray():[];
        var revision=Revision(s);
        bool paused; lock(s.Sync) paused=gdb.State==DebugState.Stopped && s.State=="Stopped";
        var errors=new List<SectionError>();
        IReadOnlyList<FrameInfo>? frames=null;
        IReadOnlyList<VariableInfo>? locals=null;
        object? registers=null;
        IReadOnlyList<BreakpointInfo>? breakpoints=null;
        ScreenInfo? screen=null;
        bool screenSynchronized=true;
        JsonElement? targetStatus=null;
        List<EvaluationInfo>? values=expressions.Length>0?[]:null;
        bool SameStop() { lock(s.Sync) return s.Gdb==gdb && gdb.State==DebugState.Stopped && s.State=="Stopped" && s.Revision==revision; }
        async Task<T?> Section<T>(string name,Func<Task<T>> action) where T:class {
            if(!paused) { errors.Add(new(name,"NOT_STOPPED","This section is unavailable while the target is not paused.",true));return null; }
            if(!SameStop()) { errors.Add(new(name,"STATE_CHANGED","Target state changed while collecting the snapshot.",true));return null; }
            try {
                var result=await action();
                if(!SameStop()) { errors.Add(new(name,"STATE_CHANGED","Target state changed before this section completed.",true));return null; }
                return result;
            } catch(OperationCanceledException) { throw; }
              catch(Exception ex) { var error=Translate(ex); errors.Add(new(name,error.Code,error.Message,error.Retryable));return null; }
        }
        foreach(var expression in expressions) {
            var before=errors.Count;
            var value=await Section("expression:"+expression,()=>gdb.EvaluateAsync(expression,ct));
            values!.Add(new(expression,value,errors.Count>before?errors[^1]:null));
        }
        if(requested.Contains("stack")) frames=await Section("stack",async()=>(IReadOnlyList<FrameInfo>)(await gdb.GetStackAsync(ct)).Select(f=>Frame(f)!).ToArray());
        if(requested.Contains("locals")) locals=await Section("locals",async()=>(IReadOnlyList<VariableInfo>)(await gdb.GetLocalsAsync(ct)).Select(Variable).ToArray());
        if(requested.Contains("registers")) registers=await Section("registers",async()=>(await gdb.GetRegistersAsync(ct)).ToArray());
        if(requested.Contains("breakpoints")) breakpoints=await Section("breakpoints",async()=>(IReadOnlyList<BreakpointInfo>)(await gdb.GetBreakpointsAsync(ct)).Select(Breakpoint).ToArray());
        try {
            var emulator=s.Emulator ?? throw new AutomationException("EMULATOR_MISSING","No emulator is attached.",true);
            targetStatus=await emulator.StatusAsync(ct);
            if(paused && (!SameStop() || targetStatus.Value.GetProperty("state").GetString() is not ("paused" or "error"))) {
                screenSynchronized=false;
                errors.Add(new("targetStatus","STATE_CHANGED","The emulator is not at the captured stopped state.",true));
            }
        } catch(OperationCanceledException) { throw; }
          catch(Exception ex) { screenSynchronized=false; var error=Translate(ex); errors.Add(new("targetStatus",error.Code,error.Message,error.Retryable)); }
        if(requested.Contains("screen")) {
            try {
                // The control reply comes from the same thread that publishes a stopped frame.
                // Confirm that it has processed the stop before reading the atomically replaced BMP.
                if(paused && !screenSynchronized) throw new AutomationException("SCREEN_UNSYNCHRONIZED","Could not synchronize the screen with the captured stopped state.",true);
                screen=await ReadScreenAsync(s,ct);
            }
            catch(OperationCanceledException) { throw; }
            catch(Exception ex) { screenSynchronized=false; var error=Translate(ex); errors.Add(new("screen",error.Code,error.Message,error.Retryable)); }
        }
        var info=Describe(s);
        var consistent=paused && SameStop() && screenSynchronized;
        if(paused && !SameStop() && !errors.Any(e=>e.Code=="STATE_CHANGED")) errors.Add(new("snapshot","STATE_CHANGED","Target state changed while reading the snapshot.",true));
        return new(s.Id,info.Revision,info.State,consistent,info.SelectedFrame,info.LastStop,info.LastStop?.Reason,frames,locals,registers,breakpoints,screen,values,errors,targetStatus);
    }

    private static async Task<ScreenInfo> ReadScreenAsync(Session s,CancellationToken ct)
    {
        var path=s.Emulator?.FramebufferPath;
        if(string.IsNullOrEmpty(path)||!File.Exists(path)) throw new AutomationException("SCREEN_UNAVAILABLE","No calculator frame has been produced yet.",true);
        await using var file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete,4096,FileOptions.Asynchronous);
        if(file.Length is <54 or >1024*1024) throw new AutomationException("INVALID_SCREEN","Unexpected framebuffer size.");
        var bytes=new byte[(int)file.Length]; await file.ReadExactlyAsync(bytes,ct);
        if(bytes[0]!=(byte)'B'||bytes[1]!=(byte)'M') throw new AutomationException("INVALID_SCREEN","Framebuffer is not a BMP.");
        var width=BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(18,4));
        var height=BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(22,4));
        if(width!=128 || Math.Abs((long)height)!=64) throw new AutomationException("INVALID_SCREEN","Expected a 128×64 calculator framebuffer.");
        return new(path,Convert.ToHexStringLower(SHA256.HashData(bytes)),"image/bmp",Convert.ToBase64String(bytes),width,(int)Math.Abs((long)height),bytes.Length);
    }

    private static async Task<ulong> AddressAsync(GdbSession gdb,string expression,CancellationToken ct)
    {
        var value=await gdb.EvaluateAsync("(unsigned long)("+expression+")",ct);
        var first=value.Split(' ',StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()??"";
        if(first.StartsWith("0x",StringComparison.OrdinalIgnoreCase)&&ulong.TryParse(first[2..],NumberStyles.HexNumber,CultureInfo.InvariantCulture,out var hex)) return hex;
        if(ulong.TryParse(first,NumberStyles.None,CultureInfo.InvariantCulture,out var number)) return number;
        throw new AutomationException("INVALID_ADDRESS","GDB did not produce a numeric address: "+Limit(value,256));
    }

    private void OnBuildLog(Session s,string line)
    {
        var text=Limit(line,8192);
        Publish(s,"build.log",new { text });
        var diagnostic=ParseDiagnostic(text);
        if(diagnostic is null)return;
        lock(s.Sync) { if(s.Diagnostics.Count<1000)s.Diagnostics.Add(diagnostic);else s.DiagnosticsTruncated=true; }
        Publish(s,"build.diagnostic",diagnostic);
    }

    internal static DiagnosticInfo? ParseDiagnostic(string text)
    {
        var match=Regex.Match(text,@"^(?<file>.+?):(?<line>\d+)(?::(?<column>\d+))?:\s*(?<severity>fatal error|error|warning|note):\s*(?<message>.*)$",RegexOptions.CultureInvariant,TimeSpan.FromMilliseconds(100));
        return !match.Success?null:new(match.Groups["severity"].Value,match.Groups["message"].Value,match.Groups["file"].Value,
            int.TryParse(match.Groups["line"].Value,out var lineNumber)?lineNumber:null,
            int.TryParse(match.Groups["column"].Value,out var column)?column:null);
    }
}
