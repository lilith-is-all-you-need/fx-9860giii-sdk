"""Rebuild the shipped GDB from its adjacent complete source package, offline.

Requires Python 3.12+ and a prepared MSYS2 MINGW64 build environment. It never
installs MSYS2 packages, changes PATH persistently, or changes system settings.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from embed_manifest import embed
from patch_source import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--msys', type=Path, default=Path('C:/msys64'))
    parser.add_argument('--work', type=Path, required=True,
                        help='New or existing build directory; ASCII, no spaces/apostrophes')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    work = args.work.resolve()
    if not str(work).isascii() or any(c in str(work) for c in " '\""):
        raise SystemExit('The GNU make build directory must use ASCII without spaces or quotes')
    archive = here / 'gdb-16.3.tar.xz'
    expected = 'bcfcd095528a987917acf9fff3f1672181694926cc18d609c99d0042c00224c5'
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise SystemExit('GNU GDB source archive SHA256 mismatch')
    work.mkdir(parents=True, exist_ok=True)
    if not (work / 'source/gdb-16.3/configure').is_file():
        with tarfile.open(archive) as source:
            source.extractall(work / 'source', filter='data')
    patch(work / 'source/gdb-16.3')
    for name in ('build.sh', 'relink.sh'):
        shutil.copy2(here / name, work / name)
    native = work.as_posix()
    posix = '/' + native[0].lower() + native[2:]
    env = dict(os.environ, MSYSTEM='MINGW64', CHERE_INVOKING='1')
    for name in ('build.sh', 'relink.sh'):
        subprocess.run([str(args.msys / 'usr/bin/bash.exe'), '--noprofile', '--norc',
                        posix + '/' + name, posix], check=True, env=env)
    target = work / 'gdb-rebuilt.exe'
    shutil.copy2(work / 'prefix/bin/sh-elf-gdb.exe', target)
    subprocess.run([str(args.msys / 'mingw64/bin/strip.exe'), '--strip-unneeded', str(target)], check=True)
    embed(target, here / 'utf8.manifest')
    print(target)


if __name__ == '__main__':
    main()
