"""Assemble the public, corresponding-source companion to the Windows release.

Run --prepare --plan first. Run without --plan after the release code is final.
The collector never starts WSL, exports user environments, or includes Casio SDK
files, ROMs, historical CAS test programs, generated build trees, or runtime
duplicates. Existing upstream hashes are verified; newly downloaded exact MSYS2
source packages are recorded with their URL, version, size, and SHA-256.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from package_components import SDK_EDITION_FILES, public_component_sources

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.2.0'
CACHE = ROOT / 'dist-toolchain/public-source-inputs'
EMU_REVISION = '63e325708e9eea53eb4769b9c057082614ebd919'
CODE_SUFFIXES = {'.cs', '.csproj', '.sln', '.slnx', '.xaml', '.json', '.xml', '.config',
                 '.props', '.targets', '.py', '.ps1', '.sh', '.c', '.h', '.cpp', '.hpp',
                 '.cmake', '.in', '.txt', '.md', '.html', '.css', '.manifest', '.patch',
                 '.png', '.svg', '.ico', '.resx', '.editorconfig', '.yaml', '.yml'}
CODE_SUFFIXES.update({'.s', '.ld', '.java'})
OMIT_DIRS = {'bin', 'obj', 'build', 'source', '__pycache__', '.git', '.vs', '.fxstudio',
             '.fxide-source', 'integration-work', 'node_modules'}
COMPRESSED = {'.xz', '.gz', '.bz2', '.zst', '.zip', '.nupkg', '.png', '.ico'}


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_file(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def pacman_desc(path):
    return {key: value.strip() for key, value in
            re.findall(r'%([^%]+)%\n([^%]*)', path.read_text())}


def prepare():
    """Prepare only explicit, public inputs; no recursive copy of user data."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dependencies = CACHE / 'native-sdk-dependencies'
    dependencies.mkdir(exist_ok=True)
    entries = []
    for name in ('mpc', 'zstd'):
        matches = [p for p in Path('C:/msys64/var/lib/pacman/local').glob(
            'mingw-w64-x86_64-' + name + '-*/desc')
            if pacman_desc(p)['NAME'] == 'mingw-w64-x86_64-' + name]
        if len(matches) != 1:
            raise RuntimeError('Cannot identify exact installed MSYS2 dependency: ' + name)
        desc = pacman_desc(matches[0])
        filename = desc['BASE'] + '-' + desc['VERSION'] + '.src.tar.zst'
        url = 'https://repo.msys2.org/mingw/sources/' + filename
        target = dependencies / filename
        if not target.is_file():
            with urllib.request.urlopen(url, timeout=120) as src, target.with_suffix('.part').open('wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            target.with_suffix('.part').replace(target)
        entries.append({'name': desc['NAME'], 'version': desc['VERSION'],
                        'license': desc['LICENSE'], 'file': filename, 'url': url,
                        'bytes': target.stat().st_size, 'sha256': sha(target)})
        (dependencies / (name + '-installed-package.desc')).write_bytes(matches[0].read_bytes())
        licenses = Path('C:/msys64/mingw64/share/licenses') / name
        if licenses.is_dir():
            shutil.copytree(licenses, dependencies / 'licenses' / name, dirs_exist_ok=True)
    (dependencies / 'manifest.json').write_text(json.dumps(entries, indent=2) + '\n')

    upstream = CACHE / ('emuCasioCalc-' + EMU_REVISION + '.tar.gz')
    subprocess.run(['git', '-C', str(ROOT / 'third_party/emuCasioCalc'), 'archive',
                    '--format=tar.gz', '--prefix=third_party/emuCasioCalc/',
                    '--output=' + str(upstream), EMU_REVISION], check=True)
    (CACHE / 'emulator-source.json').write_text(json.dumps({
        'repository': 'https://github.com/joserodpt/emuCasioCalc',
        'revision': EMU_REVISION, 'archive': upstream.name,
        'sha256': sha(upstream), 'license': 'MIT; bundled font/test assets retain their notices',
    }, indent=2) + '\n')

    # Copy exactly the resolved NuGet package, never the entire NuGet cache.
    assets = json_file(ROOT / 'src/FxStudio.App/obj/project.assets.json')
    package = 'avalonedit/6.3.1.120/avalonedit.6.3.1.120.nupkg'
    choices = [Path(p) / package for p in assets['packageFolders']]
    actual = next((p for p in choices if p.is_file()), None)
    if actual is None:
        raise RuntimeError('The resolved AvalonEdit 6.3.1.120 NuGet package is missing')
    nuget = CACHE / 'avalonedit'
    nuget.mkdir(exist_ok=True)
    shutil.copy2(actual, nuget / actual.name)
    shutil.copy2(ROOT / 'downloads/AvalonEdit-LICENSE.txt', nuget / 'LICENSE.txt')
    (nuget / 'manifest.json').write_text(json.dumps({
        'package': 'AvalonEdit', 'version': '6.3.1.120', 'license': 'MIT',
        'file': actual.name, 'sha256': sha(actual),
        'repository': 'https://github.com/icsharpcode/AvalonEdit',
        'packageUrl': 'https://www.nuget.org/packages/AvalonEdit/6.3.1.120',
    }, indent=2) + '\n')

    # The self-contained runtime comes from the locally cached official SDK.
    dotnet = CACHE / 'dotnet-notices'
    dotnet.mkdir(exist_ok=True)
    host = Path(os.environ.get('FXSTUDIO_DOTNET', 'C:/fxstudio-build/dotnet'))
    for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
        shutil.copy2(host / name, dotnet / name)
    shutil.copy2(ROOT / 'downloads/dotnet-sdk.json', dotnet / 'sdk-origin.json')
    (dotnet / 'runtime-origin.json').write_text(json.dumps({
        'runtimeVersion': '10.0.15', 'sdkVersion': '10.0.404',
        'repositories': ['https://github.com/dotnet/runtime/tree/v10.0.15',
                         'https://github.com/dotnet/wpf/tree/v10.0.15'],
        'note': 'Official SDK notices cover the runtime components; the SDK binary is not in this source archive.',
    }, indent=2) + '\n')


@dataclass
class Entry:
    name: str
    origin: str
    file: Path | None = None
    data: bytes | None = None

    def read(self):
        return self.file.read_bytes() if self.file is not None else self.data


def collect():
    entries = {}

    def add(path: Path, name=None, origin='Fx Studio source'):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Required regular source file missing or symlink: ' + str(path))
        key = name or path.relative_to(ROOT).as_posix()
        if key in entries:
            if entries[key].read() != path.read_bytes():
                raise RuntimeError('Conflicting archive path: ' + key)
            return
        entries[key] = Entry(key, origin, file=path)

    def tree(folder, origin, prefix=None, code_only=False):
        folder = ROOT / folder
        if not folder.is_dir():
            raise RuntimeError('Required source directory missing: ' + str(folder))
        for path in sorted(folder.rglob('*')):
            relative = path.relative_to(folder)
            if any(part in OMIT_DIRS for part in relative.parts[:-1]) or not path.is_file():
                continue
            if code_only and path.suffix.lower() not in CODE_SUFFIXES and path.name not in ('LICENSE', '.gitignore', 'CMakeLists.txt'):
                continue
            add(path, (Path(prefix) / relative).as_posix() if prefix else None, origin)

    def verified(path, expected, origin):
        if sha(path) != expected:
            raise RuntimeError('Recorded upstream SHA256 does not match: ' + str(path))
        add(path, origin=origin)

    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.txt', '.gitignore', '.gitattributes',
                 'README.txt', 'README.md', 'FxStudio.slnx', 'global.json'):
        add(ROOT / name)
    for folder in ('src', 'tests', 'tooling', 'docs', 'examples', 'skills', 'scaffolds', 'compat'):
        tree(folder, 'Fx Studio source', code_only=True)
    for relative in sorted(SDK_EDITION_FILES):
        add(ROOT / relative, origin='Fx Studio SDK edition')
    for relative in public_component_sources(ROOT):
        add(ROOT / relative, origin='Public Loader/emulator component snapshot')
    tree('sdk/examples', 'Fx Studio calculator examples', code_only=True)
    for name in ('BUILD-SERVICE.md', 'PROVISIONING-STATUS.md'):
        add(ROOT / 'sdk' / name)
    for path in (ROOT / 'probes/emulator').iterdir():
        if path.is_file() and path.suffix in CODE_SUFFIXES:
            add(path, origin='Fx Studio emulator bridge and debugger modifications')
    for folder in ('cpp-runtime', 'restart-runtime', 'graphics-audit'):
        tree('probes/emulator/' + folder, 'Fx Studio real calculator runtime probes', code_only=True)
    tree('source-notices', 'Public redistribution notes')

    # Import the exact Git snapshot as normal source files, without .git or an
    # additional compressed duplicate. No local research checkout is exported.
    provenance = json_file(CACHE / 'emulator-source.json')
    snapshot = CACHE / provenance['archive']
    if sha(snapshot) != provenance['sha256']:
        raise RuntimeError('Emulator snapshot SHA256 mismatch')
    with tarfile.open(snapshot) as source:
        for member in source.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or '..' in Path(member.name).parts or member.name.startswith('/'):
                raise RuntimeError('Unexpected entry in public upstream snapshot: ' + member.name)
            if Path(member.name).suffix.lower() in {'.g1a', '.g3a', '.elf', '.exe', '.dll'}:
                raise RuntimeError('Unexpected compiled fixture in upstream snapshot: ' + member.name)
            entries[member.name] = Entry(member.name, 'emuCasioCalc ' + EMU_REVISION,
                                         data=source.extractfile(member).read())
    add(CACHE / 'emulator-source.json', 'third_party/emuCasioCalc/SOURCE-ORIGIN.json', 'Upstream provenance')

    sdk = ROOT / 'dist-toolchain/sources/sdk'
    for record in json_file(sdk / 'manifest.json'):
        verified(sdk / record['file'], record['sha256'], 'Exact SDK/compiler corresponding source')
        if record.get('localPatch'):
            add(sdk / record['localPatch'], origin='SDK local patch')
    add(sdk / 'manifest.json', origin='SDK corresponding source inventory')

    gdb = ROOT / 'dist-toolchain/native-gdb'
    gdbsource = json_file(gdb / 'source-manifest.json')
    verified(gdb / gdbsource['file'], gdbsource['sha256'], 'GNU GDB source')
    for record in json_file(gdb / 'dependency-manifest.json')['sources']:
        verified(gdb / 'dependency-sources' / record['file'], record['sha256'], 'Exact MSYS2 static dependency source and recipe')
    tree('dist-toolchain/native-gdb/licenses', 'GDB and dependency license notices')
    for name in ('source-manifest.json', 'dependency-manifest.json', 'native-gdb-manifest.json',
                 'README.md', 'build.sh', 'relink.sh', 'patch_source.py', 'embed_manifest.py',
                 'rebuild.py', 'utf8.manifest'):
        add(gdb / name, origin='Native GDB configuration, local patch, provenance and rebuilding')

    host = ROOT / 'dist-toolchain/native-fxsdk'
    for record in json_file(host / 'source-archives.json'):
        verified(host / 'archives' / record['name'], record['sha256'], 'Native build-host corresponding source')
    for name in ('source-archives.json', 'host-dependencies.json', 'BUILD-MANIFEST.json', 'native-host.patch'):
        add(host / name, origin='Native fxSDK configuration and host dependency provenance')
    for path in sorted((host / 'dependency-sources').rglob('*')):
        if path.is_file() and (path.name.endswith('.src.tar.zst') or path.name in ('manifest.json', 'installed-package.desc')):
            add(path, origin='Native fxSDK exact MSYS2 libpng/zlib source package')
    tree('dist-toolchain/native-fxsdk/prefix/licenses', 'Native fxSDK library notices', 'licenses/native-fxsdk')
    add(host / 'prefix/host/python/LICENSE.txt', 'licenses/python/LICENSE.txt', 'Python and bundled component notices')
    add(host / 'prefix/host/python/Lib/site-packages/pillow-11.3.0.dist-info/licenses/LICENSE',
        'licenses/pillow/LICENSE.txt', 'Pillow wheel and bundled static dependency notices')
    cmake = host / 'prefix/host/cmake/doc/cmake'
    for path in cmake.rglob('*'):
        if path.is_file() and any(path.name.lower().startswith(p) for p in ('license', 'copying', 'notice', 'copyright')):
            add(path, 'licenses/cmake/' + path.relative_to(cmake).as_posix(), 'CMake bundled third-party notices')
    for record in json_file(CACHE / 'native-sdk-dependencies/manifest.json'):
        verified(CACHE / 'native-sdk-dependencies' / record['file'], record['sha256'], 'Exact native compiler static dependency source and recipe')
    for folder in ('native-sdk-dependencies', 'avalonedit', 'dotnet-notices'):
        tree('dist-toolchain/public-source-inputs/' + folder, 'Exact native dependency provenance and notices')
    return sorted(entries.values(), key=lambda entry: entry.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Prepare public snapshots, notices and missing exact source packages')
    parser.add_argument('--plan', action='store_true', help='Verify and report inputs without freezing a release archive')
    parser.add_argument('--output', type=Path, default=ROOT / f'dist-windows/FxStudio-{VERSION}-sources.zip')
    args = parser.parse_args()
    if not args.plan and args.output.exists():
        raise FileExistsError('Choose a new source archive path; existing release archives are preserved: ' + str(args.output))
    if args.prepare:
        prepare()
    entries = collect()
    records = []
    for entry in entries:
        data = entry.read()
        records.append({'path': entry.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'origin': entry.origin})
    manifest = {'schemaVersion': 1, 'version': VERSION, 'files': records,
                'exclusions': ['Casio official SDK/ROMs', 'historical CAS ELF/G1A fixtures',
                               'WSL rootfs/user files/Ubuntu cache', 'generated build trees',
                               'unpacked GNU source duplicates', 'runtime binary duplicates'],
                'notes': 'Read source-notices/README.md and each upstream license. Source hash inventory is not hardware validation.'}
    print(json.dumps({'files': len(records), 'bytes': sum(r['bytes'] for r in records),
                      'output': str(args.output), 'planOnly': args.plan}, indent=2), flush=True)
    if args.plan:
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.zip.partial')
    prefix = f'FxStudio-{VERSION}-sources/'
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for entry, record in zip(entries, records):
                data = entry.read()
                if hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise RuntimeError('Source changed while archiving; rerun after edits settle: ' + entry.name)
                info = zipfile.ZipInfo(prefix + entry.name, date_time=(2026, 11, 14, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED if Path(entry.name).suffix.lower() in COMPRESSED else zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
            archive.writestr(prefix + 'SOURCE-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        with zipfile.ZipFile(temporary) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError('ZIP CRC verification failed: ' + bad)
        temporary.replace(args.output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    result = {'schemaVersion': 1, 'version': VERSION, 'file': args.output.name,
              'bytes': args.output.stat().st_size, 'sha256': sha(args.output),
              'files': len(records), 'manifest': manifest}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Archive SHA256:', result['sha256'], flush=True)


if __name__ == '__main__':
    main()
