using System.Globalization;
using System.Text;

namespace FxStudio.Core;

/// <summary>A GDB/MI value, preserving repeated keys and mixed result/value lists.</summary>
public abstract record MiValue
{
    public virtual string? Text => null;
    public virtual IReadOnlyList<KeyValuePair<string, MiValue>> Fields => [];
    public virtual IReadOnlyList<MiValue> Items => [];
    public MiValue? this[string key] => Fields.FirstOrDefault(x => x.Key == key).Value;
    public string? GetString(string key) => this[key]?.Text;
    public int? GetInt(string key) => int.TryParse(GetString(key), NumberStyles.Integer,
        CultureInfo.InvariantCulture, out var value) ? value : null;
    public IEnumerable<MiValue> GetAll(string key) => Fields.Where(x => x.Key == key).Select(x => x.Value);
    public static string Quote(string value)
    {
        var output = new StringBuilder("\"");
        foreach (var c in value)
        {
            output.Append(c switch
            {
                '\\' => "\\\\", '"' => "\\\"", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
                '\0' => "\\000", _ when c < 32 => "\\" + Convert.ToString(c, 8).PadLeft(3, '0'),
                _ => c.ToString()
            });
        }
        return output.Append('"').ToString();
    }
}

public sealed record MiConst(string Value) : MiValue
{
    public override string Text => Value;
}

public sealed record MiTuple(IReadOnlyList<KeyValuePair<string, MiValue>> Values) : MiValue
{
    public override IReadOnlyList<KeyValuePair<string, MiValue>> Fields => Values;
    public static readonly MiTuple Empty = new([]);
}

public sealed record MiList(IReadOnlyList<MiValue> Values) : MiValue
{
    public override IReadOnlyList<MiValue> Items => Values;
}

public sealed record MiRecord(long? Token, char Kind, string Class, MiTuple Results, string? StreamText, string Raw)
{
    public bool IsResult => Kind == '^';
    public bool IsStream => Kind is '~' or '@' or '&';
    public string? GetString(string key) => Results.GetString(key);
}

public sealed class MiParseException(string message) : FormatException(message);

public static class MiParser
{
    public static MiRecord? Parse(string line)
    {
        if (string.IsNullOrWhiteSpace(line) || line.Trim() == "(gdb)") return null;
        return new Parser(line).ReadRecord();
    }

    private sealed class Parser(string input)
    {
        private int _position;
        private int _depth;
        private bool End => _position >= input.Length;
        private char Current => End ? '\0' : input[_position];
        private MiParseException Error(string text) => new($"{text} at offset {_position} in MI record.");

        public MiRecord ReadRecord()
        {
            var tokenStart = _position;
            while (char.IsAsciiDigit(Current)) _position++;
            long? token = null;
            if (_position != tokenStart)
            {
                if (!long.TryParse(input.AsSpan(tokenStart, _position - tokenStart), out var parsed))
                    throw Error("Invalid command token");
                token = parsed;
            }
            var kind = Current;
            if (kind is not ('^' or '*' or '+' or '=' or '~' or '@' or '&')) throw Error("Unknown record prefix");
            _position++;
            if (kind is '~' or '@' or '&')
            {
                var text = ReadString();
                RequireEnd();
                return new(token, kind, "", MiTuple.Empty, text, input);
            }
            var resultClass = ReadIdentifier();
            var results = new List<KeyValuePair<string, MiValue>>();
            while (Current == ',')
            {
                _position++;
                // MI2 emits multi-location breakpoints as bkpt={parent},{child},...
                // (unlike MI3's nested locations list). Preserve these anonymous tuples.
                results.Add(Current == '{' ? new("", ReadValue()) : ReadResult());
            }
            RequireEnd();
            return new(token, kind, resultClass, new(results), null, input);
        }

        private void RequireEnd()
        {
            while (!End && char.IsWhiteSpace(Current)) _position++;
            if (!End) throw Error("Unexpected trailing data");
        }

        private string ReadIdentifier()
        {
            var start = _position;
            while (char.IsAsciiLetterOrDigit(Current) || Current is '_' or '-') _position++;
            if (_position == start) throw Error("Expected identifier");
            return input[start.._position];
        }

        private KeyValuePair<string, MiValue> ReadResult()
        {
            var name = ReadIdentifier();
            Expect('=');
            return new(name, ReadValue());
        }

        private MiValue ReadValue()
        {
            if (++_depth > 128) throw Error("MI nesting limit exceeded");
            try
            {
                if (Current == '"') return new MiConst(ReadString());
                if (Current == '{')
                {
                    _position++;
                    var fields = new List<KeyValuePair<string, MiValue>>();
                    if (Current != '}')
                    {
                        fields.Add(ReadResult());
                        while (Current == ',') { _position++; fields.Add(ReadResult()); }
                    }
                    Expect('}');
                    return new MiTuple(fields);
                }
                if (Current == '[')
                {
                    _position++;
                    var items = new List<MiValue>();
                    if (Current != ']')
                    {
                        items.Add(ReadListItem());
                        while (Current == ',') { _position++; items.Add(ReadListItem()); }
                    }
                    Expect(']');
                    return new MiList(items);
                }
                throw Error("Expected quoted string, tuple or list");
            }
            finally { _depth--; }
        }

        private MiValue ReadListItem() => Current is '"' or '{' or '['
            ? ReadValue() : new MiTuple([ReadResult()]);

        private string ReadString()
        {
            Expect('"');
            // GDB emits UTF-8 bytes in octal escapes when print sevenbit-strings is enabled.
            // Buffer those bytes and decode together, preserving literal Unicode text.
            var output = new StringBuilder();
            var bytes = new List<byte>();
            void FlushBytes()
            {
                if (bytes.Count == 0) return;
                output.Append(Encoding.UTF8.GetString(bytes.ToArray()));
                bytes.Clear();
            }
            while (!End && Current != '"')
            {
                var c = input[_position++];
                if (c != '\\') { FlushBytes(); output.Append(c); continue; }
                if (End) throw Error("Unterminated string escape");
                c = input[_position++];
                if (c is >= '0' and <= '7')
                {
                    var value = c - '0';
                    for (var i = 1; i < 3 && Current is >= '0' and <= '7'; i++)
                        value = value * 8 + input[_position++] - '0';
                    bytes.Add((byte)value);
                    continue;
                }
                if (c == 'x')
                {
                    var start = _position;
                    while (Uri.IsHexDigit(Current)) _position++;
                    if (start == _position) throw Error("Invalid hex escape");
                    if (!byte.TryParse(input.AsSpan(start, _position - start), NumberStyles.HexNumber,
                        CultureInfo.InvariantCulture, out var value)) throw Error("Hex escape exceeds one byte");
                    bytes.Add(value);
                    continue;
                }
                FlushBytes();
                output.Append(c switch
                {
                    'n' => '\n', 'r' => '\r', 't' => '\t', 'b' => '\b', 'f' => '\f',
                    'v' => '\v', 'a' => '\a', '\\' => '\\', '"' => '"', '\'' => '\'',
                    _ => throw Error("Unknown string escape")
                });
            }
            FlushBytes();
            Expect('"');
            return output.ToString();
        }

        private void Expect(char c)
        {
            if (Current != c || End) throw Error($"Expected '{c}'");
            _position++;
        }
    }
}
