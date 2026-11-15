"""Offline native Windows fxSDK build; source and final artifacts may have Unicode paths.

Usage: python build-native.py SDK SOURCE OUTPUT Debug|Release
GNU build inputs live in a dedicated ASCII cache, never in the user's source tree.
"""
from __future__ import annotations
import ctypes
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding='utf8', errors='replace')
sys.stderr.reconfigure(encoding='utf8', errors='replace')
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('build_common', Path(__file__).with_name('build-project.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def ascii_path(path: Path, purpose: str) -> Path:
    path = path.absolute()
    if str(path).isascii() and "'" not in str(path):
        return path
    fn = ctypes.windll.kernel32.GetShortPathNameW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    fn.restype = ctypes.c_uint
    needed = fn(str(path), None, 0)
    if needed:
        buffer = ctypes.create_unicode_buffer(needed)
        if fn(str(path), buffer, needed) and buffer.value.isascii() and "'" not in buffer.value:
            return Path(buffer.value)
    raise RuntimeError(f'{purpose} needs an ASCII path on a volume without short names. '
                       'Choose a folder such as C:\\FxStudio in Settings. Project source paths may still contain Unicode.')


class BuildLock:
    def __init__(self, path: Path, wait_seconds: float = 0):
        self.path = path
        self.stream = None
        self.wait_seconds = wait_seconds

    def __enter__(self):
        self.stream = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.stream.write(b'0'); self.stream.flush()
        self.stream.seek(0)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    self.stream.close(); self.stream = None
                    raise RuntimeError('Another build is using this output directory or SDK cache.') from error
                time.sleep(0.1)
        return self

    def __exit__(self, *_):
        self.stream.seek(0)
        msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


def prepare_sdk(sdk: Path, cache: Path) -> Path:
    """Use the supplied SDK directly, or create a content-verified ASCII snapshot.

    Never require short-name support, admin rights, a drive mapping, or changes to
    the installed SDK. Distinct SDK contents get distinct compiler/build paths.
    Interrupted copies are repaired; every reused file is checked against source.
    """
    try:
        return ascii_path(sdk, 'SDK')
    except RuntimeError:
        pass
    print('Preparing native SDK cache for this installation path (offline)...', flush=True)
    records = []
    for parent, dirs, files in os.walk(sdk):
        current = Path(parent)
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in dirs + sorted(files):
            path = current / name
            if path.is_symlink() or path.is_junction():
                raise RuntimeError('SDK cache does not accept symlinks or junctions: ' + str(path))
        for name in sorted(files):
            if name.endswith('.pyc'):
                continue
            path = current / name
            relative = path.relative_to(sdk).as_posix()
            if not relative.isascii() or "'" in relative:
                raise RuntimeError('SDK internal filenames must be ASCII: ' + relative)
            records.append((relative, common.digest(path)))
    if not records:
        raise RuntimeError('Native SDK is empty: ' + str(sdk))
    identity = hashlib.sha256(json.dumps(sorted(records), separators=(',', ':')).encode()).hexdigest()
    # Reserve a namespace outside the per-project build folders. Canonical path
    # checks prevent a pre-existing link from redirecting writes outside the cache.
    store = cache / 'sdk-snapshots'
    if store.is_symlink() or store.is_junction():
        raise RuntimeError('SDK snapshot store must not be a link')
    common.contained_path(store, cache, 'SDK snapshot store')
    store.mkdir(exist_ok=True)
    lock = store / (identity + '.lock')
    if lock.is_symlink() or lock.is_junction():
        raise RuntimeError('SDK snapshot lock must not be a link')
    with BuildLock(lock, wait_seconds=60):
        destination = store / identity
        if destination.is_symlink() or destination.is_junction():
            raise RuntimeError('SDK snapshot must not be a link')
        common.contained_path(destination, store, 'SDK snapshot')
        destination.mkdir(exist_ok=True)
        copied = 0
        for relative, checksum in records:
            target = destination / relative
            common.contained_path(target, destination, 'SDK snapshot file')
            if target.is_symlink() or target.is_junction():
                raise RuntimeError('SDK snapshot file must not be a link: ' + relative)
            if target.is_file() and common.digest(target) == checksum:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.fxstudio-copy')
            common.contained_path(temporary, destination, 'SDK snapshot temporary file')
            if temporary.is_symlink() or temporary.is_junction():
                raise RuntimeError('SDK snapshot temporary file must not be a link')
            shutil.copyfile(sdk / relative, temporary)
            if common.digest(temporary) != checksum:
                raise RuntimeError('SDK changed while preparing its cache; retry the build: ' + relative)
            temporary.replace(target)
            copied += 1
            if copied % 500 == 0:
                print(f'Preparing native SDK cache: {copied}/{len(records)} files copied', flush=True)
        print(f'Native SDK cache verified: {destination} ({copied} files copied)', flush=True)
        return destination


def main():
    if len(sys.argv) != 5 or sys.argv[4] not in ('Debug', 'Release'):
        raise RuntimeError('Usage: build-native.py SDK SOURCE OUTPUT Debug|Release')
    sdk = Path(sys.argv[1]).resolve()
    source, output = [Path(value).resolve() for value in sys.argv[2:4]]
    configuration = sys.argv[4]
    if not (source / 'CMakeLists.txt').is_file():
        raise RuntimeError('Source has no CMakeLists.txt')
    if source == output or source.is_relative_to(output):
        raise RuntimeError('Output directory must not contain the source directory')
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get('FXIDE_NATIVE_WORK', str(Path(tempfile.gettempdir()) / 'FxStudio-native')))
    cache.mkdir(parents=True, exist_ok=True)
    cache = ascii_path(cache, 'Native build cache')
    canonical_cache = cache.resolve()
    for folder in (source, output, sdk):
        if canonical_cache == folder or canonical_cache.is_relative_to(folder) or folder.is_relative_to(canonical_cache):
            raise RuntimeError('Native build cache must be outside the source, final output and SDK directories')
    # Clear a previous success before any SDK snapshot preparation can fail.
    manifest = output / 'artifact.json'
    with BuildLock(output / '.fxide-native.lock'):
        manifest.unlink(missing_ok=True)
        build_project(prepare_sdk(sdk, cache), source, output, configuration, cache, manifest)


def build_project(sdk, source, output, configuration, cache, manifest):
    key = hashlib.sha256((str(source) + '\0' + str(output) + '\0' + str(sdk)).encode()).hexdigest()[:24]
    work = cache / key
    canonical_work = work.resolve()
    if canonical_work.is_relative_to(source) or source.is_relative_to(canonical_work) or canonical_work.is_relative_to(output) or output.is_relative_to(canonical_work):
        raise RuntimeError('Native build cache must be outside the source and final output directories')
    work.mkdir(exist_ok=True)
    with BuildLock(work / '.lock'):
        stage, build = work / 'source', work / 'build'
        build.mkdir(exist_ok=True)
        common.sync_source(source, stage, output)
        config_path = stage / 'fxide.json'
        config = json.loads(config_path.read_text(encoding='utf8')) if config_path.is_file() else {}
        python = sdk / 'host/python/python.exe'
        cmake = sdk / 'host/cmake/bin/cmake.exe'
        ninja = sdk / 'host/ninja/ninja.exe'
        modules = sdk / 'lib/cmake/fxsdk'
        launcher = sdk / 'service/compiler-launcher.py'
        required = [python, cmake, ninja, modules / 'FX9860G.cmake', launcher, sdk / 'bin/sh-elf-gcc.exe', sdk / 'bin/fxgxa.exe']
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError('Native SDK is incomplete: ' + ', '.join(missing))
        env = dict(os.environ)
        env.update(PATH=os.pathsep.join([str(sdk / 'bin'), str(python.parent), str(cmake.parent), str(ninja.parent), str(Path(os.environ['SystemRoot']) / 'System32')]),
                   PYTHONUTF8='1', FXIDE_NATIVE='1', FXIDE_CONFIGURATION=configuration,
                   FXIDE_COMMAND_LOG=str(build / '.fxide-compiler-commands.jsonl'))
        (build / '.fxide-compiler-commands.jsonl').unlink(missing_ok=True)
        query = build / '.cmake/api/v1/query'
        query.mkdir(parents=True, exist_ok=True)
        (query / 'codemodel-v2').touch()
        launch_arg = python.as_posix() + ';' + launcher.as_posix()
        options = ['-G', 'Ninja', f'-DCMAKE_MAKE_PROGRAM={ninja.as_posix()}',
                   f'-DCMAKE_TOOLCHAIN_FILE={(modules / "FX9860G.cmake").as_posix()}',
                   f'-DCMAKE_MODULE_PATH={modules.as_posix()}', f'-DFXSDK_CMAKE_MODULE_PATH={modules.as_posix()}',
                   f'-DPython3_EXECUTABLE={python.as_posix()}',
                   f'-DCMAKE_BUILD_TYPE={configuration}', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']
        for kind in ('C_COMPILER', 'CXX_COMPILER', 'C_LINKER', 'CXX_LINKER'):
            options.append(f'-DCMAKE_{kind}_LAUNCHER={launch_arg}')
        for name, value in config.get('cmake', {}).items():
            if not isinstance(name, str) or not name.replace('_', '').isalnum():
                raise RuntimeError('Invalid CMake option name')
            if name.startswith(('CMAKE_', 'FXSDK_', 'Python')):
                raise RuntimeError('Toolchain CMake options are managed by the IDE')
            if not isinstance(value, (str, int, float, bool)):
                raise RuntimeError('CMake option values must be scalar')
            options.append(f'-D{name}={"ON" if value is True else "OFF" if value is False else value}')
        common.run([cmake, '-S', stage, '-B', build, *options], env)
        previous = {str(p): p.stat().st_mtime_ns for folder in (stage, build) for p in folder.rglob('*.g1a')}
        name, elf = common.select_target(build, config.get('target'), validate=False)
        elf.unlink(missing_ok=True)  # select_target verified this is inside our build directory.
        common.run([cmake, '--build', build, '--target', name, '--parallel', str(min(os.cpu_count() or 2, 8))], env)
        name, elf = common.select_target(build, config.get('target'))
        if configuration == 'Debug':
            sections = subprocess.check_output([str(sdk / 'bin/sh-elf-readelf.exe'), '-SW', str(elf)], env=env, text=True)
            if '.debug_info' not in sections or '.symtab' not in sections:
                raise RuntimeError('Debug ELF is missing DWARF or symbols')
        candidates = [p for folder in (stage, build) for p in folder.rglob('*.g1a') if previous.get(str(p)) != p.stat().st_mtime_ns]
        if len(candidates) != 1:
            raise RuntimeError(f'Expected one newly generated G1A; found {len(candidates)}')
        g1a = common.contained_path(candidates[0], work, 'Generated G1A')
        pairing = common.verify_artifact_pair(elf, g1a)
        artifact_dir = common.contained_path(output / 'artifacts', output, 'Artifacts directory')
        artifact_dir.mkdir(exist_ok=True)
        # ASCII basenames let native GDB load via its Unicode working directory.
        final_elf, final_g1a = artifact_dir / 'addin.elf', artifact_dir / 'addin.g1a'
        for original, final in ((elf, final_elf), (g1a, final_g1a)):
            common.contained_path(final, output, 'Published artifact')
            temporary = final.with_suffix(final.suffix + '.tmp')
            common.contained_path(temporary, output, 'Temporary artifact')
            shutil.copy2(original, temporary)
            temporary.replace(final)
        pairing = common.verify_artifact_pair(final_elf, final_g1a)
        for record_name in ('compile_commands.json', '.fxide-compiler-commands.jsonl'):
            if (build / record_name).is_file():
                destination = common.contained_path(output / record_name, output, 'Build command record')
                shutil.copy2(build / record_name, destination)
        result = {'schemaVersion': 1, 'pathStyle': 'windows', 'elf': str(final_elf), 'g1a': str(final_g1a),
                  'sourceDirectory': str(source), 'buildDirectory': str(output), 'cacheDirectory': str(work),
                  'sourceMappings': [{'from': stage.as_posix(), 'to': str(source)}],
                  'sha256': {'elf': common.digest(final_elf), 'g1a': common.digest(final_g1a)},
                  'configuration': configuration, 'target': name, 'g1aBytes': final_g1a.stat().st_size,
                  'artifactPair': pairing, 'debugFlagsForced': configuration == 'Debug', 'hardwareVerified': False,
                  'capabilities': {'cppExceptions': False, 'cppThreads': False},
                  'toolchain': 'Native fxSDK 2.11.0 / GCC 14.1.0 / gint 2.11.0'}
        temporary_manifest = output / 'artifact.json.tmp'
        common.contained_path(temporary_manifest, output, 'Manifest')
        temporary_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        temporary_manifest.replace(manifest)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Build failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
