using System.Text;
using System.Text.Json;
using FxStudio.Agent;

Console.InputEncoding = new UTF8Encoding(false);
Console.OutputEncoding = new UTF8Encoding(false);
try
{
    string? Option(string name) { var i = Array.IndexOf(args, name); if (i < 0) return null; if (i + 1 >= args.Length) throw new ArgumentException("Missing value: " + name); return args[i + 1]; }
    if (args.Contains("--help")) { Console.WriteLine("FxStudio.Agent 0.2.0\n--stdio [--package DIR] [--data DIR]   MCP stdio server; local, offline\n--describe [--package DIR]            JSON command catalog\n--version                            Print version\nStop by closing stdin; owned debugger/emulator processes are cleaned up."); return 0; }
    if (args.Contains("--version")) { Console.WriteLine("0.2.0 (automation contract 1.0)"); return 0; }
    for (var i = 0; i < args.Length; i++) { if (args[i] is "--package" or "--data") { if (++i >= args.Length) throw new ArgumentException("Missing option value."); } else if (args[i] is not ("--stdio" or "--describe")) throw new ArgumentException("Unknown option: " + args[i]); }
    var package = Path.GetFullPath(Option("--package") ?? AppContext.BaseDirectory);
    await using var host = new AgentHost(package, Option("--data"));
    if (args.Contains("--describe")) { Console.WriteLine(JsonSerializer.Serialize(host.Discover(null), Wire.Json)); return 0; }
    using var shutdown = new CancellationTokenSource();
    Console.CancelKeyPress += (_, e) => { e.Cancel = true; shutdown.Cancel(); };
    await new McpServer(host).RunAsync(Console.In, Console.Out, shutdown.Token);
    return 0;
}
catch (OperationCanceledException) { return 0; }
catch (Exception ex) { Console.Error.WriteLine(ex.Message); return 1; }
