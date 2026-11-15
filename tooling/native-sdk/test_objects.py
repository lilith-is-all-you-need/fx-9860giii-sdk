"""Real native compiler smoke test; no emulation or synthetic object files."""
from pathlib import Path
import argparse
import json
import os
import struct
import subprocess

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ['USERPROFILE']) / '.codex-build-envs/native-sdk-20261114'
parser = argparse.ArgumentParser()
parser.add_argument('--prefix', type=Path, default=WORK/'prefix')
parser.add_argument('--report', type=Path, default=HERE/'object-smoke.json')
options = parser.parse_args()
PREFIX = options.prefix.resolve()
TEST = WORK / 'object-smoke'
TEST.mkdir(exist_ok=True)
programs = {
    'probe.c': '#include <stdint.h>\nstruct Counter { int32_t value; };\nint update(struct Counter *counter, int delta) { int old = counter->value; counter->value += delta; return old; }\n',
    'probe.cpp': '#include <array>\n#include <cstdint>\ntemplate<class T> constexpr T square(T value) { return value * value; }\nstruct Counter { std::int32_t value; int update(int delta); };\nint Counter::update(int delta) { std::array<int, 2> values{value, square(delta)}; value += values[1]; return values[0]; }\n'
}
env = dict(os.environ, PATH=os.pathsep.join([str(PREFIX/'bin'), str(Path(os.environ['WINDIR'])/'System32'), os.environ['WINDIR']]))
for name in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH'):
    env.pop(name, None)
results = []
for name, code in programs.items():
    source = TEST/name
    output = TEST/(name+'.o')
    source.write_text(code, encoding='utf-8')
    compiler = PREFIX/'bin'/('sh-elf-g++.exe' if name.endswith('.cpp') else 'sh-elf-gcc.exe')
    command = [str(compiler), '-m4-nofpu', '-mb', '-Og', '-g3', '-ffreestanding', '-fno-lto', '-c', str(source), '-o', str(output)]
    if name.endswith('.cpp'):
        command[1:1] = ['-std=c++17', '-fno-exceptions', '-fno-rtti']
    subprocess.run(command, env=env, check=True)
    header = output.read_bytes()[:52]
    assert header[:6] == b'\x7fELF\x01\x02', 'Expected ELF32 big endian'
    assert struct.unpack_from('>H', header, 18)[0] == 42, 'Expected EM_SH'
    assert struct.unpack_from('>H', header, 16)[0] == 1, 'Expected relocatable object'
    description = subprocess.check_output([str(PREFIX/'bin/sh-elf-readelf.exe'), '-h', str(output)], env=env, text=True)
    results.append({'source': name, 'command': command, 'bytes': output.stat().st_size, 'elfHeader': description})
options.report.write_text(json.dumps(results, indent=2), encoding='utf-8')
print('PASS: native Windows GCC14.1 compiles real SuperH C and C++17 debug objects with standard headers and isolated PATH')
