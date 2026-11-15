using System.Runtime.InteropServices;
using System.Text;

namespace FxStudio.Core;

/// <summary>A verified, immutable-per-session binary pair under a GNU-friendly path.</summary>
public sealed class NativeDebugImage : IAsyncDisposable
{
    public string DirectoryPath { get; }
    public BuildArtifact Artifact { get; }
    private bool _disposed;

    private NativeDebugImage(string directory, BuildArtifact artifact) { DirectoryPath = directory; Artifact = artifact; }

    public static async Task<NativeDebugImage> CreateAsync(BuildArtifact original, string? cacheRoot = null, CancellationToken ct = default)
    {
        var verified = await original.VerifyAsync(ct);
        var root = Path.GetFullPath(Path.Combine(string.IsNullOrWhiteSpace(cacheRoot) ? Path.GetTempPath() : cacheRoot, "FxStudio-debug"));
        Directory.CreateDirectory(root);
        root = AsciiDirectory(root);
        var directory = Path.Combine(root, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var image = new NativeDebugImage(directory, original with {
            ElfPath = Path.Combine(directory, "addin.elf"), G1APath = Path.Combine(directory, "addin.g1a"),
            ElfSha256 = verified.ElfSha256, G1ASha256 = verified.G1ASha256,
            LinuxElfPath = "", LinuxG1APath = ""
        });
        try {
            File.Copy(original.ElfPath, image.Artifact.ElfPath);
            File.Copy(original.G1APath, image.Artifact.G1APath);
            await image.Artifact.VerifyAsync(ct);
            return image;
        } catch { await image.DisposeAsync(); throw; }
    }

    private static string AsciiDirectory(string directory)
    {
        if (directory.All(c => c < 128)) return directory;
        if (OperatingSystem.IsWindows()) {
            var buffer = new StringBuilder(32768);
            var count = GetShortPathName(directory, buffer, buffer.Capacity);
            if (count > 0 && count < buffer.Capacity && buffer.ToString().All(c => c < 128)) return buffer.ToString();
        }
        throw new IOException("Native GDB needs an ASCII session cache on this volume. Select an ASCII native build cache in Settings; project paths may still contain Unicode.");
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "GetShortPathNameW")]
    private static extern uint GetShortPathName(string longPath, StringBuilder shortPath, int bufferLength);

    public ValueTask DisposeAsync()
    {
        if (_disposed) return ValueTask.CompletedTask;
        _disposed = true;
        // Delete only files owned by this session. Never recursively delete a cache root.
        foreach (var name in new[] { "addin.elf", "addin.g1a", "screen.bmp", "screen.bmp.tmp" }) {
            try { File.Delete(Path.Combine(DirectoryPath, name)); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
        try { Directory.Delete(DirectoryPath, recursive: false); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        return ValueTask.CompletedTask;
    }
}
