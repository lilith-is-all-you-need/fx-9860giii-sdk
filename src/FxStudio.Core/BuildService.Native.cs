using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace FxStudio.Core;

public sealed partial class BuildService
{
    private async Task<BuildArtifact> BuildNativeAsync(ProjectConfig project, BuildConfiguration configuration, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(project.NativeSdkDirectory)) throw new BuildException("Select a native SDK directory in Settings.");
        var sdk = Path.GetFullPath(project.NativeSdkDirectory);
        var python = Path.Combine(sdk, "host", "python", "python.exe");
        var script = Path.Combine(sdk, "service", "build-native.py");
        if (!File.Exists(python) || !File.Exists(script)) throw new BuildException("The native SDK is incomplete: " + sdk);
        var output = Path.Combine(project.BuildDirectory, configuration.ToString());
        Directory.CreateDirectory(output);
        var manifest = Path.Combine(output, "artifact.json");
        var startedAt = DateTime.UtcNow;
        var start = new ProcessStartInfo(python) {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var argument in new[] { script, sdk, Path.GetFullPath(project.SourceDirectory), output, configuration.ToString() }) start.ArgumentList.Add(argument);
        if (!string.IsNullOrWhiteSpace(project.NativeWorkDirectory)) start.Environment["FXIDE_NATIVE_WORK"] = Path.GetFullPath(project.NativeWorkDirectory);
        start.Environment["PYTHONUTF8"] = "1";
        EventDispatch.Raise(Log, $"Building {project.Name} ({configuration}) using native Windows SDK");
        using var process = new Process { StartInfo = start };
        if (!process.Start()) throw new BuildException("Could not start the native build service.");
        async Task ReadOutput(StreamReader stream) {
            while (await stream.ReadLineAsync(ct) is { } line) EventDispatch.Raise(Log, line);
        }
        var stdout = ReadOutput(process.StandardOutput);
        var stderr = ReadOutput(process.StandardError);
        try {
            await process.WaitForExitAsync(ct);
            await Task.WhenAll(stdout, stderr);
        } catch {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            try { await Task.WhenAll(stdout, stderr); } catch { }
            throw;
        }
        if (process.ExitCode != 0) throw new BuildException($"Native build failed with exit code {process.ExitCode}. See the build output.", process.ExitCode);
        if (!File.Exists(manifest) || File.GetLastWriteTimeUtc(manifest) < startedAt.AddSeconds(-2)) throw new BuildException("Native build did not produce a fresh artifact manifest.");
        using var document = JsonDocument.Parse(await File.ReadAllTextAsync(manifest, ct));
        var root = document.RootElement;
        if (root.GetProperty("schemaVersion").GetInt32() != 1 || root.GetProperty("pathStyle").GetString() != "windows") throw new BuildException("Unsupported native artifact manifest.");
        string FilePath(string field) {
            var value = root.GetProperty(field).GetString();
            if (string.IsNullOrWhiteSpace(value) || !Path.IsPathFullyQualified(value)) throw new BuildException("Expected absolute native path: " + field);
            var full = Path.GetFullPath(value);
            var boundary = Path.GetFullPath(output).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(boundary, StringComparison.OrdinalIgnoreCase)) throw new BuildException("Native artifact lies outside the requested build directory: " + full);
            return full;
        }
        var mappings = root.GetProperty("sourceMappings").EnumerateArray().Select(m => new SourceMapping(m.GetProperty("from").GetString()!, m.GetProperty("to").GetString()!)).ToArray();
        var artifact = new BuildArtifact {
            ElfPath = FilePath("elf"), G1APath = FilePath("g1a"), ManifestPath = manifest, Configuration = configuration,
            LinuxElfPath = "", LinuxG1APath = "", LinuxSourceDirectory = "", LinuxBuildDirectory = "",
            SourceMappings = mappings, LinuxSourceMappings = [],
            ElfSha256 = root.GetProperty("sha256").GetProperty("elf").GetString(),
            G1ASha256 = root.GetProperty("sha256").GetProperty("g1a").GetString()
        };
        await artifact.VerifyAsync(ct);
        EventDispatch.Raise(Log, $"G1A: {artifact.G1APath} ({artifact.G1ASize:N0} bytes)");
        return artifact;
    }
}
