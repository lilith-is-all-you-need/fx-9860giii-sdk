from pathlib import Path
import ctypes
import os
import subprocess
import tarfile
import shutil
from patch_source import patch

HERE=Path(__file__).resolve().parent
scratch=Path(os.environ['USERPROFILE'])/'.codex-build-envs/native-gdb-20261114'
scratch.mkdir(parents=True,exist_ok=True)
if not (scratch/'source/gdb-16.3/configure').is_file():
    with tarfile.open(HERE.parents[1]/'dist-toolchain/native-gdb/gdb-16.3.tar.xz') as archive:
        archive.extractall(scratch/'source',filter='data')
patch(scratch/'source/gdb-16.3')
shutil.copy2(HERE/'build.sh',scratch/'build.sh')
shutil.copy2(HERE/'relink.sh',scratch/'relink.sh')
native=str(scratch).replace('\\','/')
posix='/'+native[0].lower()+native[2:]
if ' ' in posix:
    raise RuntimeError('MSYS GNU build requires a path without spaces')
print('Build workspace:',posix,flush=True)
env=dict(os.environ,MSYSTEM='MINGW64',CHERE_INVOKING='1')
status=subprocess.call(['C:/msys64/usr/bin/bash.exe','--noprofile','--norc',posix+'/build.sh',posix],env=env)
if status == 0:
    status=subprocess.call(['C:/msys64/usr/bin/bash.exe','--noprofile','--norc',posix+'/relink.sh',posix],env=env)
for name in ('configure.log','build.log','install.log'):
    if (scratch/name).is_file():shutil.copy2(scratch/name,HERE/name)
raise SystemExit(status)
