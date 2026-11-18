using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using FxStudio.Core;

namespace FxStudio.Win32Host;

internal static class Program
{
    internal static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);
    private static readonly object OutputLock = new();
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetStdHandle(int id, SafeFileHandle handle);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(SafeFileHandle handle, uint mask, uint flags);
    internal static void Emit(string kind, object? data)
    {
        lock (OutputLock) Console.WriteLine(JsonSerializer.Serialize(new { kind, data }, Options));
    }

    // The input reader stays live during a build. All target-changing requests
    // run in wire order; cancellation can interrupt the current operation.
    private static async Task Main(string[] args)
    {
        Console.InputEncoding = Console.OutputEncoding = new UTF8Encoding(false);
        // SDK subprocesses must not inherit the live UI control pipe. In particular,
        // Python inspects stdin at startup while the host already owns a pending read.
        using var control = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
        using var childInput = CreateFileW("NUL", 0x80000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (childInput.IsInvalid || !SetHandleInformation(childInput, 1, 1) || !SetStdHandle(-10, childInput))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        var root = args.Length > 0 ? Path.GetFullPath(args[0]) : AppContext.BaseDirectory;
        await using var workspace = new Workspace(root);
        Task active = Task.CompletedTask;
        CancellationTokenSource? cancellation = null;
        try {
            while (await control.ReadLineAsync() is { } line) {
                JsonObject request;
                try { request = JsonNode.Parse(line)!.AsObject(); }
                catch (Exception ex) { Emit("error", ex.Message); continue; }
                string command = request["cmd"]!.GetValue<string>();
                if (command == "cancel") { cancellation?.Cancel(); continue; }
                if (command == "quit") break;
                await active;
                cancellation?.Dispose();
                cancellation = new();
                var token = cancellation.Token;
                active = Task.Run(async () => {
                    try { await workspace.Execute(command, request, token); }
                    catch (OperationCanceledException) { Emit("cancelled", command); }
                    catch (Exception ex) { Emit("error", ex.Message); }
                    finally { Emit("done", command); }
                });
            }
        } finally {
            cancellation?.Cancel();
            await active;
            cancellation?.Dispose();
        }
    }
}

internal sealed partial class Workspace(string root) : IAsyncDisposable
{
    private readonly BuildService builder = new();
    private ProjectConfig? project;
    private BuildArtifact? artifact;
    private bool imported;
    private string configFile = "";
    private JsonObject settings = new();
    private static string Text(JsonObject o, string key, string fallback = "") =>
        o[key]?.GetValue<string>() ?? fallback;
    private static int Num(JsonObject o, string key, int fallback = 0) =>
        o[key]?.GetValue<int>() ?? fallback;
    private static void Emit(string kind, object? data) => Program.Emit(kind, data);
    private static void Log(string text) => Emit("log", text);
    private static string First(params string[] values) => values.FirstOrDefault(s => !string.IsNullOrWhiteSpace(s)) ?? "";
    private string Sdk => First(project?.NativeSdkDirectory ?? "", Text(settings, "sdk"), Path.Combine(root, "sdk", "native"));
    private string Work => First(project?.NativeWorkDirectory ?? "", Text(settings, "work"));
    private string ConfigDistro => First(Text(settings, "distro"), "FxSDK-Dev-20261114");
    private ProjectConfig Project => project ?? throw new InvalidOperationException("Open a project first.");
    private BuildArtifact Artifact => artifact ?? throw new InvalidOperationException("Build the project first.");
    private static string Abs(string value, string parent) => !string.IsNullOrWhiteSpace(value)
        ? Path.GetFullPath(value, parent) : throw new InvalidDataException("Missing path in project descriptor.");

    public async Task Execute(string cmd, JsonObject a, CancellationToken ct)
    {
        switch (cmd) {
            case "open": await Open(Text(a, "path"), ct); break;
            case "settings":
                settings = a;
                if (project != null && !imported && a["applyDistro"]?.GetValue<bool>() == true) {
                    project = project with { Distro = ConfigDistro };
                    await project.SaveAsync(configFile, ct);
                }
                break;
            case "build": await Build(Text(a, "configuration", "Debug"), ct); break;
            case "export": await Export(Text(a, "path"), ct); break;
            case "invalidate": if (!imported) artifact = null; break;
            case "start":
            case "restart":
                if (cmd == "start" && debugger?.State == DebugState.Stopped) { await debugger.ContinueAsync(ct); break; }
                if (cmd == "restart") await Stop();
                if (debugger != null) throw new InvalidOperationException("Session already active.");
                if (!imported) await Build("Debug", ct);
                await Start(a, ct);
                break;
            case "stop": await Stop(); break;
            case "asset":
            case "migrate": await Tool(cmd, a, ct); break;
            default: await DebugCommand(cmd, a, ct); break;
        }
    }

    private async Task Open(string path, CancellationToken ct)
    {
        path = Path.GetFullPath(path);
        var parent = Directory.Exists(path) ? path : Path.GetDirectoryName(path)!;
        bool isBundle = path.EndsWith(".fxdebug.json", StringComparison.OrdinalIgnoreCase);
        ProjectConfig next;
        BuildArtifact? binary = null;
        string file = path.EndsWith(".fxide.json", StringComparison.OrdinalIgnoreCase) ? path : Path.Combine(parent, "project.fxide.json");
        if (isBundle) {
            var descriptor = JsonNode.Parse(await File.ReadAllTextAsync(path, ct),
                new JsonNodeOptions { PropertyNameCaseInsensitive = true })!.AsObject();
            if (Num(descriptor, "schemaVersion") != 1) throw new InvalidDataException("Unsupported debug descriptor.");
            var source = Abs(Text(descriptor, "sourceDirectory", "."), parent);
            var elf = Abs(Text(descriptor, "elf"), parent);
            next = new() { Name = Text(descriptor, "name", "SuperH"), SourceDirectory = source, BuildDirectory = Path.GetDirectoryName(elf)! };
            var mappings = descriptor["sourceMappings"]?.AsArray().Select(m => new SourceMapping(m!["from"]!.GetValue<string>(), Abs(m["to"]!.GetValue<string>(), parent))).ToArray() ?? [];
            binary = new() { ElfPath = elf, G1APath = Abs(Text(descriptor, "g1a"), parent), ManifestPath = path,
                ElfSha256 = descriptor["elfSha256"]?.GetValue<string>(), G1ASha256 = descriptor["g1aSha256"]?.GetValue<string>(),
                Configuration = BuildConfiguration.Debug, SourceMappings = mappings, LinuxElfPath = "", LinuxG1APath = "", LinuxSourceDirectory = "", LinuxBuildDirectory = "" };
            await binary.VerifyAsync(ct);
        } else {
            next = File.Exists(file) ? await ProjectConfig.LoadAsync(file, ct) : new() {
                Name = Path.GetFileName(parent), SourceDirectory = parent, BuildDirectory = Path.Combine(parent, ".fxstudio", "build"), Distro = ConfigDistro };
            if (!File.Exists(Path.Combine(next.SourceDirectory, "CMakeLists.txt"))) throw new FileNotFoundException("CMakeLists.txt is missing.");
            if (!File.Exists(file)) await next.SaveAsync(file, ct);
        }
        if (!Directory.Exists(next.SourceDirectory)) throw new DirectoryNotFoundException(next.SourceDirectory);
        await Stop();
        project = next; artifact = binary; configFile = file; imported = isBundle;
        Emit("project", new { name = next.Name, directory = next.SourceDirectory, build = next.BuildDirectory, path = isBundle ? path : file, imported });
        if (binary != null) Announce(binary);
    }

    private static void Announce(BuildArtifact result) => Emit("artifact", new {
        elf = result.ElfPath, g1a = result.G1APath, size = result.G1ASize, configuration = result.Configuration.ToString() });
    private async Task Build(string configuration, CancellationToken ct)
    {
        if (imported || debugger != null) throw new InvalidOperationException("Open an editable project and stop debugging before building.");
        artifact = null;
        // The project descriptor is an editable project file. Respect changes
        // saved in the editor or by another tool before selecting the build backend.
        var saved = await ProjectConfig.LoadAsync(configFile, ct);
        if (!string.Equals(saved.SourceDirectory, Project.SourceDirectory, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Source directory changed. Reopen the project to refresh its file tree.");
        project = saved;
        var config = Project with { NativeSdkDirectory = Sdk, NativeWorkDirectory = Work };
        if (config.Backend == "wsl" && config.BuildEntrypoint == "/opt/fxide/bin/build-project") {
            var probe = new ProcessStartInfo(config.WslExecutable) { UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardError = true, RedirectStandardOutput = true };
            foreach (var arg in new[] { "-d", config.Distro, "--exec", "/usr/bin/test", "-x", config.BuildEntrypoint })
                probe.ArgumentList.Add(arg);
            using var check = Process.Start(probe)!;
            var stderr = check.StandardError.ReadToEndAsync(ct); var stdout = check.StandardOutput.ReadToEndAsync(ct);
            try { await check.WaitForExitAsync(ct); await Task.WhenAll(stderr, stdout); }
            catch { if (!check.HasExited) check.Kill(entireProcessTree: true); throw; }
            if (check.ExitCode == 1) {
                var scripts = await builder.ToLinuxPathAsync(config, Path.Combine(root, "tooling", "wsl"), ct);
                config = config with { BuildEntrypoint = scripts + "/build-project",
                    CancelBuildEntrypoint = config.CancelBuildEntrypoint == "/opt/fxide/bin/cancel-build" ? scripts + "/cancel-build" : config.CancelBuildEntrypoint };
            }
        }
        void BuildLine(string text) {
            if (text.StartsWith("{\"schemaVersion\":") && text.Contains("\"artifactPair\"")) return;
            Log(text);
            var match = Regex.Match(text, @"^(?<file>.+?):(?<line>\d+)(?::\d+)?:\s*(?<severity>fatal error|error|warning|note):\s*(?<message>.*)$");
            if (!match.Success || !int.TryParse(match.Groups["line"].Value, out int line)) return;
            string path = match.Groups["file"].Value.Replace('\\', '/');
            int marker = path.LastIndexOf("/source/", StringComparison.OrdinalIgnoreCase);
            if (marker >= 0) path = path[(marker + 8)..];
            if (!Path.IsPathFullyQualified(path)) path = Path.GetFullPath(path, config.SourceDirectory);
            Emit("diagnostic", new { file = path, line, severity = match.Groups["severity"].Value, message = match.Groups["message"].Value });
        }
        builder.Log += BuildLine;
        try {
            artifact = await builder.BuildAsync(config, Enum.Parse<BuildConfiguration>(configuration), ct);
            await artifact.VerifyAsync(ct);
            Announce(artifact);
        } finally { builder.Log -= BuildLine; }
    }

    private async Task Export(string path, CancellationToken ct)
    {
        var item = debugImage?.Artifact ?? Artifact;
        var verified = await item.VerifyAsync(ct);
        byte[] bytes = await File.ReadAllBytesAsync(item.G1APath, ct);
        ArtifactPairVerifier.CheckExpectedSha256(Convert.ToHexString(SHA256.HashData(bytes)), verified.G1ASha256, "Exported G1A");
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { await File.WriteAllBytesAsync(temporary, bytes, ct); File.Move(temporary, path, true); }
        finally { File.Delete(temporary); }
        Emit("exported", path);
    }

    private async Task Tool(string cmd, JsonObject a, CancellationToken ct)
    {
        if (debugger != null || (cmd == "asset" && imported)) throw new InvalidOperationException("Stop debugging and open an editable project.");
        var psi = new ProcessStartInfo(Path.Combine(Sdk, "host", "python", "python.exe")) {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var arg in new[] { "-X", "utf8", Path.Combine(root, "tooling", cmd == "asset" ? "project_assets.py" : "legacy_project.py") }) psi.ArgumentList.Add(arg);
        foreach (var value in a["args"]!.AsArray()) psi.ArgumentList.Add(value!.GetValue<string>());
        ct.ThrowIfCancellationRequested();
        using var process = Process.Start(psi)!;
        // The importer owns a multi-file transaction. Always let it commit or roll back.
        var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var message = await errors; var result = await output;
        if (process.ExitCode != 0) throw new IOException(First(message, result));
        if (message.Length > 0) Log(message);
        Log(result);
        if (cmd == "asset") { artifact = null; Emit("assets", JsonNode.Parse(result)); }
        else await Open(Text(a, "destination"), ct);
    }

    public async ValueTask DisposeAsync() => await Stop();
}
