"""Check real GCC LTO object loading through the native linker plugin."""
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
parser.add_argument('--report', type=Path, default=HERE/'lto-smoke.json')
options = parser.parse_args()
prefix = options.prefix.resolve()
work = WORK/'lto-smoke'
work.mkdir(exist_ok=True)
env = dict(os.environ, PATH=os.pathsep.join([str(prefix/'bin'), str(Path(os.environ['WINDIR'])/'System32'), os.environ['WINDIR']]))
for name in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH'):
    env.pop(name, None)
sources = {
    'entry.c': 'extern int transform(int); volatile int result; void _start(void) { result=transform(3); for(;;) {} }\n',
    'other.c': 'int transform(int input) { return input*3+1; }\n'
}
compiler = prefix/'bin/sh-elf-gcc.exe'
objects = []
commands = []
for name, code in sources.items():
    source = work/name
    source.write_text(code, encoding='utf-8')
    target = work/(name+'.o')
    command = [str(compiler), '-m4-nofpu', '-mb', '-flto', '-O2', '-g', '-ffreestanding', '-c', str(source), '-o', str(target)]
    commands.append(command)
    subprocess.run(command, check=True, env=env)
    assert b'.gnu.lto' in target.read_bytes(), 'Compiler did not emit LTO sections'
    objects.append(str(target))
output = work/'linked.elf'
command = [str(compiler), '-m4-nofpu', '-mb', '-flto=auto', '-nostdlib', '-Wl,-Ttext=0x00300200', '-Wl,-e,_start', *objects, '-o', str(output)]
commands.append(command)
result = subprocess.run(command, check=True, env=env, capture_output=True, text=True)
header = output.read_bytes()[:52]
assert header[:6] == b'\x7fELF\x01\x02'
assert struct.unpack_from('>HH', header, 16) == (2, 42)
assert struct.unpack_from('>I', header, 24)[0] == 0x00300200
report = {'commands': commands, 'linkedBytes': output.stat().st_size, 'entry': '0x00300200', 'stderr': result.stderr, 'isolatedPath': env['PATH']}
options.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('PASS: native GCC14.1/linker plugin link actual SuperH slim LTO objects with isolated PATH')
