from pathlib import Path
import hashlib
import json
import struct

HERE = Path(__file__).resolve().parent
PREFIX = HERE.parents[1]/'dist-toolchain/native-sdk'

def imports(path):
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0'
    sections, optional_size = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
    optional = pe+24
    magic = struct.unpack_from('<H', data, optional)[0]
    directory = optional+(112 if magic == 0x20b else 96)
    import_rva = struct.unpack_from('<I', data, directory+8)[0]
    ranges = []
    for index in range(sections):
        offset = optional+optional_size+40*index
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from('<IIII', data, offset+8)
        ranges.append((virtual_address, virtual_address+max(virtual_size, raw_size), raw_pointer))
    def raw(rva):
        for begin, end, pointer in ranges:
            if begin <= rva < end:
                return pointer+rva-begin
        raise ValueError(f'Invalid PE RVA in {path}')
    result = []
    if import_rva:
        offset = raw(import_rva)
        while any(data[offset:offset+20]):
            name = raw(struct.unpack_from('<I', data, offset+12)[0])
            result.append(data[name:data.index(0,name)].decode('ascii'))
            offset += 20
    return data, result

files = list((PREFIX/'bin').glob('sh-elf-*.exe'))
files += list((PREFIX/'libexec/gcc/sh3eb-elf/14.1.0').glob('*.exe'))
files += list((PREFIX/'libexec/gcc/sh3eb-elf/14.1.0').glob('*.dll'))
files += [PREFIX/'bin/libwinpthread-1.dll']
records = []
for path in sorted(files):
    data, dlls = imports(path)
    records.append({'path':path.relative_to(PREFIX).as_posix(), 'bytes':len(data),
                    'sha256':hashlib.sha256(data).hexdigest(), 'imports':dlls})
(HERE/'pe-imports.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
print(f'Audited {len(records)} native compiler, binutils and dependency PE files')
