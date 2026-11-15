"""Copy only compiler/runtime files and test without developer tools on PATH."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ['USERPROFILE'])/'.codex-build-envs/native-sdk-20261114'
source = WORK/'prefix'
target = WORK/'relocated-sdk'
(target/'bin').mkdir(parents=True, exist_ok=True)
for item in (source/'bin').glob('sh-elf-*.exe'):
    shutil.copy2(item, target/'bin'/item.name)
shutil.copy2(source/'bin/libwinpthread-1.dll', target/'bin/libwinpthread-1.dll')
for subtree in ('lib/gcc/sh3eb-elf', 'libexec/gcc/sh3eb-elf', 'sh3eb-elf'):
    shutil.copytree(source/subtree, target/subtree, dirs_exist_ok=True)
env = dict(os.environ, PATH=os.pathsep.join([str(target/'bin'), str(Path(os.environ['WINDIR'])/'System32'), os.environ['WINDIR']]))
for name in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH'):
    env.pop(name, None)
locations = {}
for flag in ('-print-prog-name=cc1', '-print-prog-name=cc1plus', '-print-file-name=libgcc.a', '-print-prog-name=liblto_plugin.dll'):
    value = subprocess.check_output([str(target/'bin/sh-elf-gcc.exe'), flag], env=env, text=True).strip()
    resolved = Path(value).resolve()
    assert resolved.is_relative_to(target), f'Relocated compiler searched original tree: {value}'
    assert resolved.is_file(), f'Relocated dependency is absent: {value}'
    locations[flag] = str(resolved)
subprocess.run([sys.executable, str(HERE/'test_objects.py'), '--prefix', str(target), '--report', str(HERE/'relocation-object-smoke.json')], check=True)
subprocess.run([sys.executable, str(HERE/'test_lto.py'), '--prefix', str(target), '--report', str(HERE/'relocation-lto-smoke.json')], check=True)
subprocess.run([sys.executable, str(HERE/'test_gint.py'), '--prefix', str(target), '--report', str(HERE/'relocation-gint-smoke.json')], check=True)
(HERE/'relocation-locations.json').write_text(json.dumps(locations, indent=2), encoding='utf-8')
print('PASS: relocated native compiler uses relocated cc1/cc1plus/libgcc/plugin and passes C/C++/LTO checks')
