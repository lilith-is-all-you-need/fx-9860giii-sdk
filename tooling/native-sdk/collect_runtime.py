"""Collect the tested native SDK without development-only Unix install scripts."""
from pathlib import Path
import hashlib
import gzip
import io
import json
import os
import shutil
import subprocess
import tarfile
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = Path(os.environ['USERPROFILE'])/'.codex-build-envs/native-sdk-20261114'
PREFIX = WORK/'prefix'
DEST = ROOT/'dist-toolchain/native-sdk'
DEST.mkdir(parents=True, exist_ok=True)
if any(DEST.iterdir()) and '--resume' not in sys.argv:
    raise RuntimeError('Collection destination is not empty; keep previous releases immutable and choose a fresh destination.')

def is_notice(path):
    name = path.name.lower()
    return any(word in name for word in ('copying', 'copyright', 'license', 'licence', 'notice'))

def runtime_file(relative):
    parts = relative.parts
    if '__pycache__' in parts or relative.suffix in ('.pyc', '.la'):
        return False
    if parts[0] == 'share' or 'install-tools' in parts:
        return False
    if parts[0] == 'libexec':
        return relative.suffix in ('.exe', '.dll')
    if parts[:2] == ('lib', 'bfd-plugins'):
        return False
    if parts[:2] == ('lib', 'gcc') and 'plugin' in parts:
        return False
    if parts[:2] == ('host', 'cmake') and 'doc' in parts:
        return is_notice(relative)
    if parts[0] == 'sh3eb-elf' and relative.name.endswith('-gdb.py'):
        return False
    return parts[0] in ('bin', 'host', 'lib', 'libexec', 'sh3eb-elf', 'service', 'licenses')

for source in PREFIX.rglob('*'):
    if source.is_file() and runtime_file(source.relative_to(PREFIX)):
        target = DEST/source.relative_to(PREFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

licenses = DEST/'licenses'
for source_tree in (ROOT/'dist-toolchain/native-fxsdk/prefix/licenses',
                    ROOT/'dist-toolchain/public-source-inputs/native-sdk-dependencies/licenses'):
    shutil.copytree(source_tree, licenses, dirs_exist_ok=True)
for name in ('gcc-libs', 'winpthreads', 'crt', 'libiconv'):
    shutil.copytree(ROOT/'dist-toolchain/native-gdb/licenses'/name, licenses/name, dirs_exist_ok=True)

def extract_notices(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for member in archive.getmembers():
        if member.isfile() and is_notice(Path(member.name)):
            # Preserve archive-relative paths, rejecting traversal rather than extracting blindly.
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('Unsafe license member')
            target = destination/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())

for name, pattern in [('gcc14', 'gcc-14.1.0.tar.xz'), ('binutils', 'binutils-2.42.tar.xz'),
                      ('gint', 'gint-*.tar.gz'), ('fxlibc', 'fxlibc-*.tar.gz'), ('OpenLibm', 'OpenLibm-*.tar.gz')]:
    source = next((ROOT/'dist-toolchain/sources/sdk').glob(pattern))
    with tarfile.open(source) as archive:
        # Large GNU trees only need their root license texts; target libraries have per-file notices too.
        if name in ('gcc14', 'binutils'):
            for member in archive:
                if member.isfile() and len(Path(member.name).parts) == 2 and is_notice(Path(member.name)):
                    target = licenses/name/Path(member.name).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        else:
            extract_notices(archive, licenses/name)

tar_exe = str(Path(os.environ['WINDIR'])/'System32/tar.exe')
for name, source, inner in [
    ('gmp', ROOT/'dist-toolchain/native-gdb/dependency-sources/mingw-w64-gmp-6.3.0-2.src.tar.zst', 'mingw-w64-gmp/gmp-6.3.0.tar.xz'),
    ('mpfr', ROOT/'dist-toolchain/native-gdb/dependency-sources/mingw-w64-mpfr-4.2.2-1.src.tar.zst', 'mingw-w64-mpfr/mpfr-4.2.2.tar.xz'),
    ('mpc', ROOT/'dist-toolchain/public-source-inputs/native-sdk-dependencies/mingw-w64-mpc-1.3.1-2.src.tar.zst', 'mingw-w64-mpc/mpc-1.3.1.tar.gz')]:
    extracted = subprocess.run([tar_exe, '-xOf', str(source), inner], capture_output=True)
    data = extracted.stdout
    if extracted.returncode:
        # Older Windows bsdtar can report its zstd helper's broken pipe after
        # extracting the selected member. Accept only a complete gzip member
        # whose CRC is independently validated; otherwise preserve the error.
        if not inner.endswith('.tar.gz'):
            extracted.check_returncode()
        try:
            gzip.decompress(data)
        except Exception:
            extracted.check_returncode()
            raise
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.isfile() and len(Path(member.name).parts) == 2 and is_notice(Path(member.name)):
                target = licenses/name/Path(member.name).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())

notice = '''Native fxSDK runtime

Compiler: GNU GCC 14.1.0 (sh3eb-elf, sh-elf-* command names).
Binary utilities: GNU binutils 2.42. Target headers/libraries are the fixed
gint, fxlibc, OpenLibm and GCC runtime snapshot; per-file hashes and source
identities accompany the source archive. GNU compiler components are GPLv3+
and relevant target runtime components carry the GCC Runtime Library Exception.
Other component notices are under licenses and in the host Python/Pillow/CMake
directories. The bundled libwinpthread-1.dll must remain available in both bin
and sh3eb-elf/bin. Source and build recipes are shipped with the outer release.

Deployment requires Windows 10 x64. The IDE automatically caches SDK installations
that lack a GNU-compatible path, and stages user projects to support Chinese,
spaces and apostrophes. The build cache needs an ASCII path or short alias.
Native final links use -flto-partition=none because preserved zlib LTO archives
and native zstd LTO streams cannot safely use GCC14.1's intermediate partition
copying path. User Debug source is compiled with -Og -g3 -fno-lto; SDK archives
remain unmodified and require linker-plugin support.
'''
(DEST/'NOTICE.txt').write_text(notice, encoding='utf-8')
records = []
for file in sorted(DEST.rglob('*')):
    if file.is_file() and file.name != 'manifest.json':
        records.append({'path': file.relative_to(DEST).as_posix(), 'bytes': file.stat().st_size,
                        'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
manifest = {'schemaVersion': 1, 'compiler': 'GCC 14.1.0', 'target': 'sh3eb-elf',
            'binutils': '2.42', 'files': records, 'totalBytes': sum(f['bytes'] for f in records)}
(DEST/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(f'Collected {len(records)} files, {manifest["totalBytes"]:,} bytes into {DEST}')
