using System.Buffers.Binary;
using System.Security.Cryptography;

namespace FxStudio.Core;

public sealed record ArtifactVerificationIssue(string Code, string Message, long? ElfOffset = null,
    long? G1AOffset = null, uint? Address = null);
public sealed record ArtifactLoadSegment(int Index, uint VirtualAddress, uint LoadAddress,
    uint ElfOffset, uint FileBytes, uint MemoryBytes, long G1AOffset);
public sealed record ArtifactPairVerification(bool IsMatch, IReadOnlyList<ArtifactVerificationIssue> Issues,
    IReadOnlyList<ArtifactLoadSegment> Segments, string ElfSha256, string G1ASha256,
    int PayloadBytes, int ComparedBytes)
{
    public void ThrowIfInvalid()
    {
        if (!IsMatch) throw new ArtifactPairMismatchException(this);
    }
}

public sealed class ArtifactPairMismatchException(ArtifactPairVerification verification)
    : Exception("ELF/G1A verification failed: " + string.Join("; ", verification.Issues.Select(x => x.Message)))
{
    public ArtifactPairVerification Verification { get; } = verification;
}

/// <summary>Checks the loaded ELF bytes against the actual packaged G1A, not symbol names or timestamps.</summary>
public static class ArtifactPairVerifier
{
    public const uint RomBase = 0x00300200;
    public const int G1AHeaderBytes = 512;
    // Deployment budget supported by the recorded OS 03.70.0200 size probe;
    // this is not a claim about the exact recognition limit of every Casio OS.
    public const int MaximumG1ABytes = 2_000_000;
    private const long MaximumElfBytes = 512L * 1024 * 1024;

    public static async Task<ArtifactPairVerification> VerifyAsync(string elfPath, string g1aPath,
        CancellationToken cancellationToken = default)
    {
        var elfSize = new FileInfo(elfPath).Length;
        var g1aSize = new FileInfo(g1aPath).Length;
        if (elfSize > MaximumElfBytes) throw new InvalidDataException("ELF exceeds the 512 MiB inspection limit.");
        if (g1aSize > MaximumG1ABytes) return new(false,
            [new("g1a-size-limit", $"G1A is {g1aSize} bytes, above the SDK's provisional {MaximumG1ABytes}-byte deployment budget.")],
            [], "", "", checked((int)Math.Min(g1aSize - G1AHeaderBytes, int.MaxValue)), 0);
        var elfTask = File.ReadAllBytesAsync(elfPath, cancellationToken);
        var g1aTask = File.ReadAllBytesAsync(g1aPath, cancellationToken);
        await Task.WhenAll(elfTask, g1aTask);
        cancellationToken.ThrowIfCancellationRequested();
        return Verify(elfTask.Result, g1aTask.Result);
    }

    public static async Task<ArtifactPairVerification> VerifyOrThrowAsync(string elfPath, string g1aPath,
        CancellationToken cancellationToken = default)
    {
        var result = await VerifyAsync(elfPath, g1aPath, cancellationToken);
        result.ThrowIfInvalid();
        return result;
    }

    public static ArtifactPairVerification Verify(ReadOnlySpan<byte> elf, ReadOnlySpan<byte> g1a)
    {
        var issues = new List<ArtifactVerificationIssue>();
        var segments = new List<ArtifactLoadSegment>();
        var elfHash = Convert.ToHexStringLower(SHA256.HashData(elf));
        var g1aHash = Convert.ToHexStringLower(SHA256.HashData(g1a));
        var payloadSize = Math.Max(0, g1a.Length - G1AHeaderBytes);
        var compared = 0;
        ArtifactPairVerification Result() => new(issues.Count == 0, issues, segments, elfHash, g1aHash, payloadSize, compared);
        void Issue(string code, string message, long? elfOffset = null, long? g1aOffset = null, uint? address = null) =>
            issues.Add(new(code, message, elfOffset, g1aOffset, address));

        if (elf.Length < 52) Issue("elf-header", "ELF is truncated before its 52-byte ELF32 header.");
        else
        {
            if (!elf[..4].SequenceEqual(new byte[] { 0x7f, (byte)'E', (byte)'L', (byte)'F' })) Issue("elf-magic", "ELF signature is invalid.");
            if (elf[4] != 1) Issue("elf-class", "Expected ELF32 (32-bit SuperH).");
            if (elf[5] != 2) Issue("elf-endian", "Expected big-endian ELF data.");
            if (elf[6] != 1 || U32(elf, 20) != 1) Issue("elf-version", "Unsupported ELF version.");
            if (U16(elf, 16) != 2) Issue("elf-type", "Expected a linked ELF executable (ET_EXEC).");
            if (U16(elf, 18) != 42) Issue("elf-machine", "ELF machine is not SuperH (EM_SH=42).");
            if (U16(elf, 40) != 52) Issue("elf-header-size", "ELF32 header size is not 52 bytes.");
        }
        if (g1a.Length <= G1AHeaderBytes) Issue("g1a-header", "G1A does not contain a 512-byte header and a nonempty payload.");
        if (g1a.Length > MaximumG1ABytes) Issue("g1a-size-limit", $"G1A exceeds the SDK's provisional {MaximumG1ABytes}-byte deployment budget.");
        if (issues.Count > 0) return Result();

        Span<byte> header = stackalloc byte[32];
        for (var i = 0; i < header.Length; i++) header[i] = (byte)~g1a[i];
        if (!header[..8].SequenceEqual("USBPower"u8)) Issue("g1a-magic", "G1A's inverted USBPower signature is invalid.", g1aOffset: 0);
        if (header[8] != 0xf3) Issue("g1a-type", "G1A's MCS type is not an add-in (0xf3).", g1aOffset: 8);
        if (!header.Slice(9, 5).SequenceEqual(new byte[] { 0, 0x10, 0, 0x10, 0 }) || header[15] != 1)
            Issue("g1a-sequence", "G1A's fixed sequence bytes are invalid.", g1aOffset: 9);
        if (U32(header, 16) != (uint)g1a.Length || U32(g1a, 0x1f0) != (uint)g1a.Length)
            Issue("g1a-length", $"G1A header length fields do not match actual size {g1a.Length}.", g1aOffset: 16);
        if (header[14] != (byte)(g1a.Length + 0x41) || header[20] != (byte)(g1a.Length + 0xb8))
            Issue("g1a-control", "G1A control bytes do not match its file size.", g1aOffset: 14);
        var checksum = 0;
        for (var i = 0x300; i < 0x310; i += 2)
            checksum = (checksum + (i < g1a.Length ? g1a[i] << 8 : 0) + (i + 1 < g1a.Length ? g1a[i + 1] : 0)) & 0xffff;
        if (U16(header, 22) != checksum) Issue("g1a-checksum", $"G1A header checksum differs: header 0x{U16(header, 22):X4}, calculated 0x{checksum:X4}.", g1aOffset: 22);

        var phoff = U32(elf, 28);
        var phsize = U16(elf, 42);
        var phcount = U16(elf, 44);
        if (phcount == 0 || phcount == ushort.MaxValue || phsize < 32 || phoff < 52 ||
            (ulong)phoff + (ulong)phcount * phsize > (ulong)elf.Length)
        {
            Issue("elf-program-headers", "ELF program-header table is absent, unsupported or outside the file.", phoff);
            return Result();
        }
        var covered = new bool[payloadSize];
        for (var i = 0; i < phcount; i++)
        {
            var entry = checked((int)(phoff + (uint)i * phsize));
            if (U32(elf, entry) != 1) continue; // PT_LOAD only; debug sections stay in the ELF.
            var offset = U32(elf, entry + 4);
            var vaddr = U32(elf, entry + 8);
            var paddr = U32(elf, entry + 12);
            var fileBytes = U32(elf, entry + 16);
            var memoryBytes = U32(elf, entry + 20);
            var alignment = U32(elf, entry + 28);
            if (fileBytes > memoryBytes || (ulong)offset + fileBytes > (ulong)elf.Length ||
                (ulong)vaddr + memoryBytes > 0x1_0000_0000UL || (ulong)paddr + fileBytes > 0x1_0000_0000UL)
            {
                Issue("elf-segment-bounds", $"PT_LOAD {i} has invalid file/memory sizes or overflows its address range.", offset, address: paddr);
                continue;
            }
            if (alignment > 1 && ((alignment & (alignment - 1)) != 0 || vaddr % alignment != offset % alignment))
            {
                Issue("elf-segment-alignment", $"PT_LOAD {i} has invalid alignment.", entry, address: paddr);
                continue;
            }
            if (fileBytes == 0) continue; // NOBITS/BSS has no G1A bytes to compare.
            var payloadOffset = (long)paddr - RomBase;
            var g1aOffset = G1AHeaderBytes + payloadOffset;
            segments.Add(new(i, vaddr, paddr, offset, fileBytes, memoryBytes, g1aOffset));
            if (payloadOffset < 0 || payloadOffset + fileBytes > payloadSize)
            {
                Issue("g1a-segment-bounds", $"PT_LOAD {i} at LMA 0x{paddr:X8}, {fileBytes} bytes, extends outside the G1A payload.", offset, g1aOffset, paddr);
                continue;
            }
            long? mismatch = null;
            var overlap = false;
            for (var n = 0; n < fileBytes; n++)
            {
                var destination = checked((int)(payloadOffset + n));
                if (covered[destination]) overlap = true;
                else { covered[destination] = true; compared++; }
                if (mismatch is null && elf[checked((int)(offset + n))] != g1a[G1AHeaderBytes + destination]) mismatch = n;
            }
            if (overlap) Issue("elf-segment-overlap", $"PT_LOAD {i} overlaps another loaded ROM segment.", offset, g1aOffset, paddr);
            if (mismatch is { } difference)
            {
                var elfByte = elf[checked((int)(offset + difference))];
                var g1aByte = g1a[checked((int)(g1aOffset + difference))];
                Issue("payload-mismatch", $"PT_LOAD {i} differs at address 0x{paddr + difference:X8}: ELF +0x{offset + difference:X} = 0x{elfByte:X2}, G1A +0x{g1aOffset + difference:X} = 0x{g1aByte:X2}.",
                    offset + difference, g1aOffset + difference, checked((uint)(paddr + difference)));
            }
        }
        if (segments.Count == 0) Issue("elf-no-load-data", "ELF has no nonempty PT_LOAD data.");
        if (segments.Count > 0)
        {
            var first = segments.Min(s => (long)s.LoadAddress - RomBase);
            var end = segments.Max(s => (long)s.LoadAddress - RomBase + s.FileBytes);
            if (first != 0 || end != payloadSize)
                Issue("payload-extent", $"ELF loaded ROM extent [{first}, {end}) does not equal G1A payload [0, {payloadSize}).");
            for (var i = 0; i < covered.Length; i++)
            {
                // objcopy pads gaps between allocated load segments with zero bytes.
                if (!covered[i] && g1a[G1AHeaderBytes + i] != 0)
                {
                    Issue("payload-gap-data", $"G1A has nonzero byte 0x{g1a[G1AHeaderBytes + i]:X2} at +0x{G1AHeaderBytes + i:X}, outside every ELF load segment.",
                        g1aOffset: G1AHeaderBytes + i, address: RomBase + (uint)i);
                    break;
                }
            }
        }
        var elfEntry = U32(elf, 24);
        if (elfEntry != RomBase) Issue("elf-entry", $"ELF entry 0x{elfEntry:X8} differs from the G1A entry 0x{RomBase:X8}.", 24, address: elfEntry);
        return Result();
    }

    public static void CheckExpectedSha256(string actual, string? expected, string label)
    {
        if (expected is null) return;
        if (expected.Length != 64 || !expected.All(Uri.IsHexDigit))
            throw new InvalidDataException($"Manifest {label} SHA-256 is not a 64-digit hexadecimal value.");
        if (!actual.Equals(expected, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"{label} SHA-256 mismatch: manifest {expected}, actual {actual}. The artifact changed after it was built.");
    }

    private static ushort U16(ReadOnlySpan<byte> data, int offset) => BinaryPrimitives.ReadUInt16BigEndian(data.Slice(offset, 2));
    private static uint U32(ReadOnlySpan<byte> data, int offset) => BinaryPrimitives.ReadUInt32BigEndian(data.Slice(offset, 4));
}
