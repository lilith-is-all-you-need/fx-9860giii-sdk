from pathlib import Path
import os
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = Path(os.environ['USERPROFILE']) / '.codex-build-envs/native-sdk-20261114'
WORK.mkdir(parents=True, exist_ok=True)
for name in ('binutils-2.42', 'gcc-14.1.0'):
    target = WORK / 'source' / name
    if not (target / '.extraction-complete').exists():
        print(f'Extracting {name}', flush=True)
        with tarfile.open(ROOT / 'dist-toolchain/sources/sdk' / (name + '.tar.xz')) as archive:
            archive.extractall(WORK / 'source', filter='data')
        (target / '.extraction-complete').touch()
shutil.copy2(HERE / 'build.sh', WORK / 'build.sh')
shutil.copy2(HERE / 'build_lto.sh', WORK / 'build_lto.sh')
native = str(WORK).replace('\\', '/')
posix = '/' + native[0].lower() + native[2:]
if ' ' in posix or "'" in posix:
    raise RuntimeError('GNU build workspace must have an ASCII path without spaces or quotes')
print('Native SDK build:', WORK, flush=True)
env = dict(os.environ, MSYSTEM='MINGW64', CHERE_INVOKING='1')
status = subprocess.call(['C:/msys64/usr/bin/bash.exe', '--noprofile', '--norc', posix + '/build.sh', posix], env=env)
for log in WORK.glob('*.log'):
    shutil.copy2(log, HERE / log.name)
raise SystemExit(status)
