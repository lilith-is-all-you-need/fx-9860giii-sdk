using System.Buffers.Binary;
using System.IO.Compression;

namespace FxStudio.Agent;

/// <summary>Encodes the emulator's uncompressed RGB framebuffer without native imaging dependencies.</summary>
internal static class ScreenPng
{
    internal static byte[] ConvertBmp(byte[] bmp)
    {
        if (bmp.Length < 54 || bmp[0] != 'B' || bmp[1] != 'M') throw new InvalidDataException("Invalid framebuffer BMP.");
        int U32(int offset) => BinaryPrimitives.ReadInt32LittleEndian(bmp.AsSpan(offset, 4));
        var pixelOffset = U32(10); var width = U32(18); var signedHeight = U32(22);
        var bits = BinaryPrimitives.ReadUInt16LittleEndian(bmp.AsSpan(28, 2));
        if (U32(14) < 40 || width is < 1 or > 1024 || signedHeight is < -1024 or 0 or > 1024 || bits is not (24 or 32) || U32(30) != 0 || pixelOffset < 54)
            throw new InvalidDataException("Expected an uncompressed 24/32-bit framebuffer BMP.");
        var height = Math.Abs(signedHeight); var stride = checked(((width * bits + 31) / 32) * 4);
        if ((long)pixelOffset + (long)height * stride > bmp.Length) throw new InvalidDataException("Truncated framebuffer.");
        using var output = new MemoryStream(); output.Write([137, 80, 78, 71, 13, 10, 26, 10]);
        var header = new byte[13]; BinaryPrimitives.WriteInt32BigEndian(header, width); BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(4), height); header[8] = 8; header[9] = 2;
        Chunk(output, "IHDR"u8, header);
        using var compressed = new MemoryStream();
        using (var zlib = new ZLibStream(compressed, CompressionLevel.Fastest, leaveOpen: true))
        {
            var row = new byte[1 + width * 3];
            for (var y = 0; y < height; y++)
            {
                var source = pixelOffset + (signedHeight > 0 ? height - 1 - y : y) * stride;
                for (var x = 0; x < width; x++) { var p = source + x * (bits / 8); row[1 + x * 3] = bmp[p + 2]; row[2 + x * 3] = bmp[p + 1]; row[3 + x * 3] = bmp[p]; }
                zlib.Write(row);
            }
        }
        Chunk(output, "IDAT"u8, compressed.ToArray()); Chunk(output, "IEND"u8, []); return output.ToArray();
    }
    private static void Chunk(Stream output, ReadOnlySpan<byte> type, ReadOnlySpan<byte> data)
    {
        Span<byte> number = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(number, data.Length); output.Write(number); output.Write(type); output.Write(data);
        uint crc = 0xffffffff;
        foreach (var b in type) crc = Update(crc, b);
        foreach (var b in data) crc = Update(crc, b);
        BinaryPrimitives.WriteUInt32BigEndian(number, crc ^ 0xffffffff); output.Write(number);
    }
    private static uint Update(uint crc, byte value) { crc ^= value; for (var i = 0; i < 8; i++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0u); return crc; }
}
