"""Reject stale emulator binaries before assembling a release or Loader suite."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from package_components import digest, source_file

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '63e325708e9eea53eb4769b9c057082614ebd919'
BRIDGE_SOURCES = (
    'hardware_model.c', 'hardware_model.h', 'heap_compat.h', 'memory_compat.h',
    'fx_syscalls.h', 'file_map_compat.h', 'file_address_compat.h', '../os-map-profile.h',
    '../os-map-hashes.h', 'recovery.h', 'syscall_trace.c', 'syscall_trace.h',
    'bridge.c', 'bridge_platform.c', 'bridge_compat.h', 'compat.h', 'debug_bridge.h',
    'prepare_sources.py', 'build-bridge.ps1',
)


def verify_emulator_build(root, build_dir):
    root, build_dir = Path(root).resolve(), Path(build_dir).resolve()
    record = json.loads(source_file(build_dir, 'BUILD-MANIFEST.json').read_text(encoding='utf-8-sig'))
    problems = []
    if record.get('upstreamCommit') != UPSTREAM:
        problems.append('unrecognized upstream revision')
    if record.get('executable') != 'FxEmulator.exe':
        problems.append('unexpected executable name')
    executable = source_file(build_dir, 'FxEmulator.exe')
    if record.get('sha256') != digest(executable) or record.get('bytes') != executable.stat().st_size:
        problems.append('FxEmulator.exe differs from its build manifest')
    entries = record.get('bridgeSources', [])
    hashes = {entry['name']: entry['sha256'] for entry in entries}
    if len(hashes) != len(entries) or set(hashes) != set(BRIDGE_SOURCES):
        problems.append('bridge source inventory is incomplete or unexpected')
    for name in BRIDGE_SOURCES:
        relative = (Path('probes/emulator') / name).as_posix()
        if hashes.get(name) != digest(source_file(root, relative)):
            problems.append('source changed after build: ' + relative)
    generated = record.get('generatedPatches')
    for name, field in (('debugger-hooks.patch', 'sourcePatchSha256'),
                        ('runtime-compat.patch', 'compatibilityPatchSha256')):
        # An isolated rebuild retains its newly generated patches beside the
        # binary. They are outputs; the authoritative generator is pinned above.
        patch = source_file(build_dir, name) if generated is not None else source_file(root, 'probes/emulator/' + name)
        if record.get(field) != digest(patch) or (generated is not None and generated.get(name) != digest(patch)):
            problems.append('generated patch changed after build: ' + name)
    upstream_sources = record.get('upstreamSources')
    if upstream_sources is not None:
        upstream_root = root / 'third_party/emuCasioCalc/src'
        expected_paths = {p.relative_to(root).as_posix() for p in upstream_root.rglob('*') if p.is_file()}
        if set(upstream_sources) != expected_paths or not expected_paths:
            problems.append('upstream source inventory is incomplete or unexpected')
        for relative, expected in upstream_sources.items():
            if digest(source_file(root, relative)) != expected:
                problems.append('upstream source changed after build: ' + relative)
    if problems:
        raise ValueError('Emulator build is not current:\n' + '\n'.join(problems))
    return {'passed': True, 'emulatorSha256': record['sha256'], 'sourceFiles': len(BRIDGE_SOURCES) + 2}


def copy_verified_emulator(root, build_dir, output):
    result = verify_emulator_build(root, build_dir)
    build_dir, output = Path(build_dir), Path(output)
    record = json.loads((build_dir / 'BUILD-MANIFEST.json').read_text(encoding='utf-8-sig'))
    names = ['FxEmulator.exe', 'BUILD-MANIFEST.json']
    if record.get('generatedPatches') is not None:
        names.extend(('debugger-hooks.patch', 'runtime-compat.patch'))
    output.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(build_dir / name, output / name)
    (output / 'SOURCE-VALIDATION.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'probes/emulator/build')
    args = parser.parse_args()
    try:
        print(json.dumps(verify_emulator_build(args.root, args.build_dir), indent=2))
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
