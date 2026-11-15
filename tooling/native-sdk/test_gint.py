"""Link a real add-in against the reused Linux-built gint/libc archives."""
from pathlib import Path
import argparse
import json
import os
import struct
import subprocess

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ['USERPROFILE'])/'.codex-build-envs/native-sdk-20261114'
parser = argparse.ArgumentParser()
parser.add_argument('--prefix', type=Path, default=WORK/'prefix')
parser.add_argument('--report', type=Path, default=HERE/'gint-smoke.json')
options = parser.parse_args()
prefix = options.prefix.resolve()
work = WORK/'gint-smoke'
work.mkdir(exist_ok=True)
env = dict(os.environ, PATH=os.pathsep.join([str(prefix/'bin'), str(Path(os.environ['WINDIR'])/'System32'), os.environ['WINDIR']]))
for name in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH'):
    env.pop(name, None)
source = work/'main.c'
source.write_text('#include <gint/display.h>\nint main(void) { dclear(C_WHITE); dtext(2,2,C_BLACK,"Native SDK"); dupdate(); return 0; }\n', encoding='utf-8')
compiler = prefix/'bin/sh-elf-gcc.exe'
obj = work/'main.o'
commands = [[str(compiler), '-mb', '-Og', '-g3', '-fno-lto', '-fno-builtin', '-nostdlib', '-Wa,--dsp', '-DTARGET_FX9860G', '-DFX9860G', '-c', str(source), '-o', str(obj)]]
subprocess.run(commands[0], check=True, env=env)
output = work/'gint-smoke.elf'
commands.append([str(compiler), '-mb', '-Og', '-g3', '-nostdlib', '-flto=auto', '-flto-partition=none',
                 '-Wl,--no-warn-rwx-segments', '-T', str(prefix/'sh3eb-elf/lib/fx9860g.ld'), str(obj),
                 '-Wl,--start-group', '-lgint-fx', '-lc', '-lopenlibm', '-lgcc', '-Wl,--end-group', '-o', str(output)])
result = subprocess.run(commands[-1], check=True, env=env, capture_output=True, text=True)
header = output.read_bytes()[:52]
assert header[:6] == b'\x7fELF\x01\x02'
assert struct.unpack_from('>HH', header, 16) == (2,42)
assert struct.unpack_from('>I', header, 24)[0] == 0x00300200
report = {'commands': commands, 'elfBytes': output.stat().st_size, 'entry': '0x00300200', 'stderr': result.stderr, 'isolatedPath': env['PATH']}
options.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('PASS: native compiler links actual preserved gint/libc/OpenLibm/libgcc archives with isolated PATH')
