"""Build and test current emulator sources in a new directory, preserving all runtimes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_emulator_build import BRIDGE_SOURCES, ROOT, UPSTREAM, verify_emulator_build
from package_components import digest, source_file, public_component_sources


def build(output, compiler, python, test=True):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new isolated build directory: ' + str(output))
    upstream = ROOT / 'third_party/emuCasioCalc'
    if (upstream / '.git').exists():
        revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        changes = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain', '--', 'src', 'tests'], text=True)
        if revision != UPSTREAM or changes:
            raise ValueError('Emulator upstream must be the pinned, unmodified source revision')
    else:
        origin = json.loads((upstream / 'SOURCE-ORIGIN.json').read_text(encoding='utf-8-sig'))
        if origin.get('revision') != UPSTREAM:
            raise ValueError('Unexpected upstream source origin')
    # Copy only maintained public source inputs. Existing build caches, private
    # games/firmware and running installation directories are never traversed.
    source_paths = {str(Path('probes/emulator') / name) for name in BRIDGE_SOURCES}
    # Regression checks compare shared profile/header copies from the reviewed
    # public component snapshots as well as the emulator's direct C inputs.
    source_paths.update(public_component_sources(ROOT))
    for path in (ROOT / 'probes/emulator').iterdir():
        if path.is_file() and path.suffix.lower() in {'.py', '.ps1', '.c', '.h', '.patch', '.json', '.md'}:
            source_paths.add(path.relative_to(ROOT).as_posix())
    upstream_paths = set()
    for folder in ('src', 'tests'):
        for path in (upstream / folder).rglob('*'):
            if path.is_file():
                relative = path.relative_to(ROOT).as_posix()
                source_paths.add(relative)
                if folder == 'src':
                    upstream_paths.add(relative)
    source_paths.add('third_party/emuCasioCalc/LICENSE')
    inputs = {relative: digest(source_file(ROOT, relative)) for relative in source_paths}
    output.mkdir(parents=True)
    for relative in sorted(source_paths):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (output / 'third_party/emuCasioCalc/SOURCE-ORIGIN.json').write_text(
        json.dumps({'revision': UPSTREAM, 'source': 'isolated copy of pinned public checkout'}) + '\n', encoding='utf-8')
    script = 'test-runtime.ps1' if test else 'build-bridge.ps1'
    powershell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not powershell:
        raise RuntimeError('PowerShell is required to run the existing emulator build recipe')
    command = [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(output / 'probes/emulator' / script), '-Compiler', str(compiler), '-Python', str(python)]
    environment = os.environ.copy()
    # Windows PowerShell 5 cannot use PowerShell 7's inherited module directory.
    if Path(powershell).name.lower() == 'powershell.exe':
        environment['PSMODULEPATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/Modules')
    log_path = output / 'build-and-regression.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=output, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        process.wait()
    if process.returncode:
        raise RuntimeError('Isolated emulator build/regression failed; retained output: ' + str(output))
    for relative, expected in inputs.items():
        if digest(ROOT / relative) != expected:
            raise ValueError('Source changed during build: ' + relative)
    build_dir = output / 'probes/emulator/build'
    manifest_path = build_dir / 'BUILD-MANIFEST.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    manifest['generatedPatches'] = {}
    for name in ('debugger-hooks.patch', 'runtime-compat.patch'):
        shutil.copy2(output / 'probes/emulator' / name, build_dir / name)
        manifest['generatedPatches'][name] = digest(build_dir / name)
    manifest['upstreamSources'] = {relative: inputs[relative] for relative in sorted(upstream_paths)}
    manifest['isolatedBuild'] = {'runtimeRegressionPassed': bool(test), 'buildScript': script}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    result = verify_emulator_build(ROOT, build_dir)
    result.update(buildDir=str(build_dir), runtimeRegressionPassed=bool(test))
    (build_dir / 'SOURCE-VALIDATION.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, default=Path('C:/msys64/mingw64/bin/gcc.exe'))
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    build(args.output, args.compiler, args.python, not args.build_only)


if __name__ == '__main__':
    main()
