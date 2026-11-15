using System.Text.Json;

namespace FxStudio.Core;

public enum BuildConfiguration { Debug, Release }

public sealed record ProjectConfig
{
    public int SchemaVersion { get; init; } = 1;
    public string Name { get; init; } = "My Add-in";
    public required string SourceDirectory { get; init; }
    public required string BuildDirectory { get; init; }
    public string Distro { get; init; } = "FxSDK-Dev-20261114";
    public string WslExecutable { get; init; } = "wsl.exe";
    public string BuildEntrypoint { get; init; } = "/opt/fxide/bin/build-project";
    public string CancelBuildEntrypoint { get; init; } = "/opt/fxide/bin/cancel-build";
    public string GdbExecutable { get; init; } = "/usr/bin/gdb-multiarch";
    public string Backend { get; init; } = "auto";
    public string NativeSdkDirectory { get; init; } = "";
    public string NativeWorkDirectory { get; init; } = "";

    public static async Task<ProjectConfig> LoadAsync(string path, CancellationToken ct = default)
    {
        await using var file = File.OpenRead(path);
        var config = await JsonSerializer.DeserializeAsync<ProjectConfig>(file, JsonOptions, ct)
            ?? throw new InvalidDataException("Project configuration is empty.");
        if (config.SchemaVersion != 1) throw new InvalidDataException("Unsupported project configuration version.");
        if (config.Backend is not ("auto" or "native" or "wsl")) throw new InvalidDataException("Build backend must be auto, native or wsl.");
        var root = Path.GetDirectoryName(Path.GetFullPath(path))!;
        return config with
        {
            SourceDirectory = Path.GetFullPath(config.SourceDirectory, root),
            BuildDirectory = Path.GetFullPath(config.BuildDirectory, root),
            NativeSdkDirectory = string.IsNullOrWhiteSpace(config.NativeSdkDirectory) ? "" : Path.GetFullPath(config.NativeSdkDirectory, root),
            NativeWorkDirectory = string.IsNullOrWhiteSpace(config.NativeWorkDirectory) ? "" : Path.GetFullPath(config.NativeWorkDirectory, root)
        };
    }

    public async Task SaveAsync(string path, CancellationToken ct = default)
    {
        var directory = Path.GetDirectoryName(Path.GetFullPath(path))!;
        Directory.CreateDirectory(directory);
        var temporary = Path.Combine(directory, "." + Path.GetFileName(path) + "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            var portable = this with
            {
                SourceDirectory = Path.GetRelativePath(directory, Path.GetFullPath(SourceDirectory, directory)),
                BuildDirectory = Path.GetRelativePath(directory, Path.GetFullPath(BuildDirectory, directory)),
                NativeSdkDirectory = string.IsNullOrWhiteSpace(NativeSdkDirectory) ? "" : Path.GetRelativePath(directory, Path.GetFullPath(NativeSdkDirectory, directory)),
                NativeWorkDirectory = string.IsNullOrWhiteSpace(NativeWorkDirectory) ? "" : Path.GetRelativePath(directory, Path.GetFullPath(NativeWorkDirectory, directory))
            };
            await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(portable, JsonOptions), ct);
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true
    };
}

public sealed record BuildArtifact
{
    public required string ElfPath { get; init; }
    public required string G1APath { get; init; }
    public required string LinuxElfPath { get; init; }
    public required string LinuxG1APath { get; init; }
    public required string LinuxSourceDirectory { get; init; }
    public required string LinuxBuildDirectory { get; init; }
    public required string ManifestPath { get; init; }
    public required BuildConfiguration Configuration { get; init; }
    public string? ElfSha256 { get; init; }
    public string? G1ASha256 { get; init; }
    public IReadOnlyList<SourceMapping> SourceMappings { get; init; } = [];
    public IReadOnlyList<SourceMapping> LinuxSourceMappings { get; init; } = [];
    public long G1ASize => new FileInfo(G1APath).Length;

    public async Task<ArtifactPairVerification> VerifyAsync(CancellationToken cancellationToken = default)
    {
        var result = await ArtifactPairVerifier.VerifyOrThrowAsync(ElfPath, G1APath, cancellationToken);
        ArtifactPairVerifier.CheckExpectedSha256(result.ElfSha256, ElfSha256, "ELF");
        ArtifactPairVerifier.CheckExpectedSha256(result.G1ASha256, G1ASha256, "G1A");
        return result;
    }

    public GdbLaunchOptions CreateWslGdbOptions(ProjectConfig project, int port) => new()
    {
        ExecutablePath = project.WslExecutable,
        Arguments = ["-d", project.Distro, "--", "/usr/bin/env", "LC_ALL=C.UTF-8", project.GdbExecutable, "--interpreter=mi2", "--quiet", "--nx"],
        ElfPath = LinuxElfPath, Port = port, SourceMappings = SourceMappings, GdbSourceMappings = LinuxSourceMappings
    };

    public GdbLaunchOptions CreateNativeGdbOptions(string executable, int port) => new()
    {
        ExecutablePath = File.Exists(executable) ? Path.GetFullPath(executable) : executable,
        ElfPath = Path.GetFileName(ElfPath), WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(ElfPath)),
        Port = port, SourceMappings = SourceMappings,
        PreferredBreakpointSourceRoots = LinuxSourceMappings.Select(x => x.From).ToArray()
    };
}
