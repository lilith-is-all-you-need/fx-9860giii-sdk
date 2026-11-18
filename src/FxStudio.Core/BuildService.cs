using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace FxStudio.Core;

public sealed class BuildException(string message, int? exitCode = null) : Exception(message)
{
    public int? ExitCode { get; } = exitCode;
}

public sealed partial class BuildService
{
    private readonly SemaphoreSlim _buildLock = new(1, 1);
    public event Action<string>? Log;

    public async Task<BuildArtifact> BuildAsync(ProjectConfig project, BuildConfiguration configuration,
        CancellationToken cancellationToken = default)
    {
        await _buildLock.WaitAsync(cancellationToken);
        try
        {
            if (!Directory.Exists(project.SourceDirectory)) throw new DirectoryNotFoundException(project.SourceDirectory);
            if (!File.Exists(Path.Combine(project.SourceDirectory, "CMakeLists.txt")))
                throw new BuildException("The selected project does not contain CMakeLists.txt.");
            if (project.Backend is not ("auto" or "native" or "wsl")) throw new BuildException("Unknown build backend: " + project.Backend);
            if (project.Backend == "native" || (project.Backend == "auto" && !string.IsNullOrWhiteSpace(project.NativeSdkDirectory)))
                return await BuildNativeAsync(project, configuration, cancellationToken);
            var source = await ToLinuxPathAsync(project, project.SourceDirectory, cancellationToken);
            var buildPath = Path.Combine(project.BuildDirectory, configuration.ToString());
            Directory.CreateDirectory(buildPath);
            var build = await ToLinuxPathAsync(project, buildPath, cancellationToken);
            var manifest = Path.Combine(buildPath, "artifact.json");
            // The Linux wrapper owns the per-directory lock and removes its old manifest.
            // Do not delete another process's artifact before acquiring that lock.
            var startedAt = DateTime.UtcNow;
            EventDispatch.Raise(Log, $"Building {project.Name} ({configuration}) using {project.Distro}");
            ProcessResult result;
            try
            {
                result = await RunWslAsync(project, [project.BuildEntrypoint, source, build, configuration.ToString()],
                    true, cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Killing wsl.exe alone can leave Linux compiler children alive. The SDK's
                // cancellation helper validates and terminates this build's process group.
                using var cleanupTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                try
                {
                    var cancelled = await RunWslAsync(project, [project.CancelBuildEntrypoint, build], true, cleanupTimeout.Token);
                    if (cancelled.ExitCode != 0) EventDispatch.Raise(Log, "Build cancellation helper reported: " + cancelled.Error);
                }
                catch (Exception ex) { EventDispatch.Raise(Log, "Could not confirm Linux build cancellation: " + ex.Message); }
                throw;
            }
            if (result.ExitCode != 0) throw new BuildException($"Build failed with exit code {result.ExitCode}. See the build output.", result.ExitCode);
            if (!File.Exists(manifest)) throw new BuildException("Build exited successfully but artifact.json was not produced.");
            if (File.GetLastWriteTimeUtc(manifest) < startedAt.AddSeconds(-2))
                throw new BuildException("Build did not refresh artifact.json; refusing an earlier build's output.");
            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(manifest, cancellationToken));
            var root = document.RootElement;
            if (root.GetProperty("schemaVersion").GetInt32() != 1) throw new BuildException("Unsupported artifact manifest version.");
            var elf = RequiredPath(root, "elf");
            var g1a = RequiredPath(root, "g1a");
            var linuxSource = RequiredPath(root, "sourceDirectory");
            var linuxBuild = RequiredPath(root, "buildDirectory");
            var winElf = await ToWindowsPathAsync(project, elf, cancellationToken);
            var winG1a = await ToWindowsPathAsync(project, g1a, cancellationToken);
            if (!File.Exists(winElf)) throw new BuildException("Debug ELF listed in artifact.json does not exist: " + winElf);
            if (!File.Exists(winG1a)) throw new BuildException("G1A listed in artifact.json does not exist: " + winG1a);
            var verification = await ArtifactPairVerifier.VerifyOrThrowAsync(winElf, winG1a, cancellationToken);
            if (root.TryGetProperty("sha256", out var expectedHashes))
            {
                if (expectedHashes.ValueKind != JsonValueKind.Object || !expectedHashes.TryGetProperty("elf", out var expectedElf) ||
                    !expectedHashes.TryGetProperty("g1a", out var expectedG1a) || expectedElf.ValueKind != JsonValueKind.String || expectedG1a.ValueKind != JsonValueKind.String)
                    throw new BuildException("Manifest sha256 must contain ELF and G1A hash strings.");
                ArtifactPairVerifier.CheckExpectedSha256(verification.ElfSha256, expectedElf.GetString(), "ELF");
                ArtifactPairVerifier.CheckExpectedSha256(verification.G1ASha256, expectedG1a.GetString(), "G1A");
            }
            var linuxMappings = new List<SourceMapping>();
            var uiMappings = new List<SourceMapping> { new(linuxSource, project.SourceDirectory) };
            if (root.TryGetProperty("sourceMappings", out var mappings))
            {
                foreach (var mapping in mappings.EnumerateArray())
                {
                    var from = RequiredPath(mapping, "from");
                    var to = RequiredPath(mapping, "to");
                    linuxMappings.Add(new(from, to));
                    uiMappings.Add(new(from, await ToWindowsPathAsync(project, to, cancellationToken)));
                }
            }
            var artifact = new BuildArtifact
            {
                ElfPath = winElf, G1APath = winG1a, LinuxElfPath = elf, LinuxG1APath = g1a,
                LinuxSourceDirectory = linuxSource, LinuxBuildDirectory = linuxBuild, ManifestPath = manifest,
                Configuration = configuration, SourceMappings = uiMappings, LinuxSourceMappings = linuxMappings,
                ElfSha256 = verification.ElfSha256, G1ASha256 = verification.G1ASha256
            };
            EventDispatch.Raise(Log, $"G1A: {artifact.G1APath} ({artifact.G1ASize:N0} bytes)");
            return artifact;
        }
        finally { _buildLock.Release(); }
    }

    public async Task<string> ToLinuxPathAsync(ProjectConfig project, string path, CancellationToken ct = default)
    {
        var result = await ConvertWslPathAsync(project, "-u", Path.GetFullPath(path), ct);
        if (result.ExitCode != 0) throw new BuildException("WSL could not translate a Windows path: " + result.Error, result.ExitCode);
        return SinglePath(result.Output);
    }

    public async Task<string> ToWindowsPathAsync(ProjectConfig project, string path, CancellationToken ct = default)
    {
        var result = await ConvertWslPathAsync(project, "-w", path, ct);
        if (result.ExitCode != 0) throw new BuildException("WSL could not translate a Linux path: " + result.Error, result.ExitCode);
        return SinglePath(result.Output);
    }

    private static string RequiredPath(JsonElement root, string property)
    {
        var path = root.GetProperty(property).GetString();
        if (string.IsNullOrWhiteSpace(path) || !path.StartsWith('/'))
            throw new BuildException($"Manifest field '{property}' must be an absolute Linux path.");
        return path;
    }

    private async Task<ProcessResult> ConvertWslPathAsync(ProjectConfig project, string mode, string path, CancellationToken ct)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(15));
        try { return await RunWslAsync(project, ["wslpath", "-a", mode, path], false, timeout.Token); }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) {
            throw new BuildException("WSL did not respond within 15 seconds. Check the selected distribution or use the bundled native SDK.");
        }
    }

    private static string SinglePath(string output)
    {
        var trimmed = output.TrimEnd('\r', '\n');
        if (trimmed.Length == 0 || trimmed.Contains('\n') || trimmed.Contains('\r'))
            throw new BuildException("WSL path conversion did not produce exactly one path.");
        return trimmed;
    }

    private async Task<ProcessResult> RunWslAsync(ProjectConfig project, IReadOnlyList<string> arguments,
        bool log, CancellationToken ct)
    {
        var start = new ProcessStartInfo(project.WslExecutable)
        {
            RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false,
            CreateNoWindow = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        start.ArgumentList.Add("-d"); start.ArgumentList.Add(project.Distro); start.ArgumentList.Add("--exec");
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        if (!process.Start()) throw new BuildException("Could not start WSL.");
        var stdout = new StringBuilder();
        var stderr = new StringBuilder();
        async Task ReadAsync(StreamReader stream, StringBuilder destination)
        {
            while (await stream.ReadLineAsync(ct) is { } line)
            {
                destination.AppendLine(line);
                if (log) EventDispatch.Raise(Log, line);
            }
        }
        var outputTask = Task.Run(() => ReadAsync(process.StandardOutput, stdout));
        var errorTask = Task.Run(() => ReadAsync(process.StandardError, stderr));
        try
        {
            await process.WaitForExitAsync(ct);
            await Task.WhenAll(outputTask, errorTask);
            return new(process.ExitCode, stdout.ToString(), stderr.ToString());
        }
        catch
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            // Observe both readers after cancellation to prevent unobserved stream failures.
            try { await Task.WhenAll(outputTask, errorTask); } catch { }
            throw;
        }
    }

    private sealed record ProcessResult(int ExitCode, string Output, string Error);
}
