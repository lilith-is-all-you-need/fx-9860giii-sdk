"""Assemble redistributable files only; fail if required validation is absent."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from sync_engineering_skill import sync
from package_components import copy_loader_runtime, copy_development_runtime, loader_artifact_hashes
from check_emulator_build import verify_emulator_build, copy_verified_emulator
from collect_public_sources import collect as collect_source_entries

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '.git', '*.pyc'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--dotnet-sdk', type=Path, required=True)
    parser.add_argument('--loader-artifacts', type=Path, default=ROOT / 'loader-artifacts')
    parser.add_argument('--emulator-build', type=Path, default=ROOT / 'probes/emulator/build')
    parser.add_argument('--source-archive', type=Path, default=ROOT / 'dist-windows/FxStudio-0.2.0-sources.zip')
    parser.add_argument('--name', default='FxStudio-0.2.0-win-x64')
    args = parser.parse_args()
    sync(check=True)
    verify_emulator_build(ROOT, args.emulator_build)
    loader_artifact_hashes(args.loader_artifacts)
    if Path(args.name).name != args.name or args.name in ('.', '..'):
        raise RuntimeError('Package name must be a folder name')
    validation = ROOT / 'sdk/native-validation.json'
    if not validation.exists() or not json.loads(validation.read_text()).get('passed'):
        raise RuntimeError('Native C/C++ toolchain validation has not passed')
    for required in ('sdk/relocation-validation.json', 'sdk/native-validation/native-build-contract.json', 'sdk/unicode-sdk-validation.json',
                     'research/ui-native-validation.json', 'probes/emulator/build/cpp-runtime/results.json',
                     'sdk/automation-validation.json', 'research/ui-0.2.0-validation.json',
                     'research/agent-transport-validation.json'):
        if not json.loads((ROOT / required).read_text(encoding='utf8')).get('passed'):
            raise RuntimeError('Required validation did not pass: ' + required)
    ui_evidence = json.loads((ROOT/'research/ui-0.2.0-validation.json').read_text(encoding='utf8'))
    if digest(args.app/'FxStudio.dll') != ui_evidence['appSha256']:
        raise RuntimeError('Desktop application changed after UI validation')
    for evidence_file in ('sdk/automation-validation.json','research/agent-transport-validation.json'):
        record = json.loads((ROOT/evidence_file).read_text(encoding='utf8'))
        for name, expected in record['binarySha256'].items():
            if digest(args.app/name) != expected:
                raise RuntimeError('Automation binary changed after validation: ' + name)
    source_archive = args.source_archive
    source_record = json.loads(source_archive.with_suffix('.manifest.json').read_text(encoding='utf8'))
    if digest(source_archive) != source_record['sha256']:
        raise RuntimeError('Corresponding-source archive does not match its manifest')
    recorded_sources = {row['path']: row['sha256'] for row in source_record['manifest']['files']}
    current_sources = {entry.name: hashlib.sha256(entry.read()).hexdigest() for entry in collect_source_entries()}
    changed_sources = sorted(name for name in set(recorded_sources) | set(current_sources)
                             if recorded_sources.get(name) != current_sources.get(name))
    if changed_sources:
        raise RuntimeError('Corresponding-source archive is stale; regenerate it from the final sources: '
                           + ', '.join(changed_sources[:12]))
    gdb_root = ROOT / 'dist-toolchain/native-gdb'
    gdb_manifest = json.loads((gdb_root / 'native-gdb-manifest.json').read_text(encoding='utf-8-sig'))
    gdb = gdb_root / gdb_manifest['executable']
    if digest(gdb) != gdb_manifest['sha256']:
        raise RuntimeError('GDB changed after validation')
    target = ROOT / 'dist-windows' / args.name
    target.mkdir(parents=True, exist_ok=False)
    copy_tree(args.app, target)
    copy_tree(args.sdk, target / 'sdk/native')
    copy_tree(gdb_root / 'runtime', target / 'runtime')
    emu_target = target / 'runtime/emulator'
    copy_verified_emulator(ROOT, args.emulator_build, emu_target)
    copy_loader_runtime(ROOT, args.loader_artifacts, target)
    copy_development_runtime(ROOT, target)
    copy_tree(ROOT / 'docs', target / 'docs')
    copy_tree(ROOT / 'skills', target / 'skills')
    copy_tree(ROOT / 'scaffolds', target / 'scaffolds')
    (target / 'automation').mkdir()
    shutil.copy2(ROOT / 'tooling/fxstudio_client.py', target / 'automation/fxstudio_client.py')
    shutil.copy2(ROOT / 'tooling/engineering.py', target / 'automation/engineering.py')
    for example in ('counter-c', 'counter-cpp'):
        source = ROOT / 'examples' / example
        shutil.copytree(source, target / 'examples' / example,
                        ignore=shutil.ignore_patterns('.fxstudio', 'project.fxide.json', 'build*'))
        manifest = json.loads((source / '.fxstudio/build/Debug/artifact.json').read_text(encoding='utf8'))
        prebuilt = target / 'examples/prebuilt' / example
        prebuilt.mkdir(parents=True)
        for key, name in (('elf', 'addin.elf'), ('g1a', 'addin.g1a')):
            original = Path(manifest[key])
            if digest(original) != manifest['sha256'][key]:
                raise RuntimeError('Prebuilt example changed since its build: ' + str(original))
            shutil.copy2(original, prebuilt / name)
        descriptor = {'schemaVersion': 1, 'name': example + ' (prebuilt Debug)', 'elf': 'addin.elf', 'g1a': 'addin.g1a',
                      'sourceDirectory': '../../' + example, 'elfSha256': manifest['sha256']['elf'], 'g1aSha256': manifest['sha256']['g1a'],
                      'sourceMappings': [{'from': m['from'], 'to': '../../' + example} for m in manifest['sourceMappings']]}
        (prebuilt / 'demo.fxdebug.json').write_text(json.dumps(descriptor, indent=2), encoding='utf8')
    for file in ('LICENSE', 'THIRD-PARTY-NOTICES.txt'):
        shutil.copy2(ROOT / file, target)
    licenses = target / 'licenses'
    (licenses / 'dotnet').mkdir(parents=True)
    shutil.copy2(ROOT / 'downloads/AvalonEdit-LICENSE.txt', licenses)
    shutil.copy2(ROOT / 'third_party/emuCasioCalc/LICENSE', licenses / 'emuCasioCalc-LICENSE.txt')
    for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
        shutil.copy2(args.dotnet_sdk / name, licenses / 'dotnet' / name)
    copy_tree(gdb_root / 'licenses', licenses / 'gdb')
    shutil.copy2(validation, target / 'sdk/native-validation.json')
    evidence = target / 'validation'; evidence.mkdir()
    shutil.copy2(ROOT/'research/automation-core-validation.log', evidence/'automation-core.log')
    for original, name in ((ROOT/'sdk/relocation-validation.json', 'relocation.json'),
                           (ROOT/'sdk/unicode-sdk-validation.json', 'unicode-sdk.json'),
                           (ROOT/'probes/emulator/build/restart-runtime/results.json', 'restart-runtime.json'),
                           (ROOT/'sdk/native-validation/native-build-contract.json', 'failure-cancellation.json'),
                           (ROOT/'research/ui-native-validation.json', 'native-ui.json'),
                           (ROOT/'probes/emulator/build/native-examples/results.json', 'native-examples.json'),
                           (ROOT/'probes/emulator/build/cpp-runtime/results.json', 'cpp-runtime.json'),
                           (ROOT/'sdk/automation-validation.json', 'automation.json'),
                           (ROOT/'research/ui-0.2.0-validation.json', 'ui-0.2.0.json'),
                           (ROOT/'research/agent-transport-validation.json', 'agent-transport.json'),
                           (ROOT/'probes/emulator/graphics-audit/results/results.json', 'graphics-audit.json')):
        shutil.copy2(original, evidence / name)
    (target / 'sources').mkdir()
    shutil.copy2(source_archive, target / 'sources' / source_archive.name)
    shutil.copy2(source_archive.with_suffix('.manifest.json'), target / 'sources' / source_archive.with_suffix('.manifest.json').name)
    for name in ('Verify-Package.ps1',):
        shutil.copy2(ROOT / 'tooling' / name, target / name)
    (target / 'START-HERE.txt').write_text(
        'Fx Studio 0.2.0 - Windows x64\n\nRun FxStudio.exe. Native SDK, GDB and emulator are bundled.\n'
        'Open docs/USER-GUIDE.zh-CN.html or docs/USER-GUIDE.en.html.\n'
        'See docs/VALIDATION.html for tested capabilities and remaining limits.\n'
        'Automation: FxStudio.Agent.exe --stdio (MCP); see docs/AUTOMATION.md.\n'
        'Skill (no client MCP setup): skills/fxstudio; see its references/quickstart.zh-CN.md.\n'
        'Matching corresponding sources and notices are included under sources/.\n', encoding='utf8')
    manifest = {'schemaVersion': 1, 'name': args.name, 'files': []}
    for path in sorted(target.rglob('*')):
        if path.is_file():
            manifest['files'].append({'path': path.relative_to(target).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
    (target / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    archive = target.parent / (target.name + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(target.rglob('*')):
            if path.is_file():
                zipped.write(path, args.name + '/' + path.relative_to(target).as_posix(),
                             compress_type=zipfile.ZIP_STORED if path.suffix.lower() == '.zip' else zipfile.ZIP_DEFLATED)
    archive.with_suffix('.zip.sha256').write_text(digest(archive) + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'directory': str(target), 'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest(archive)}, indent=2))


if __name__ == '__main__':
    main()
