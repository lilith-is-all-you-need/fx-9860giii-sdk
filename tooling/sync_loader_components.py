"""Sync pinned component sources into the offline SDK.

The unified Loader repository owns two source manifests. Its large/ subtree is
projected into one optional source example and the ordinary mapped Loader.
Historical three-component locks can still be refreshed from split checkouts.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from package_components import EXAMPLE, SDK_EDITION_FILES, source_file

ROOT = Path(__file__).resolve().parents[1]
UNIFIED = 'fx_universal_loader'
UNIFIED_URL = 'https://github.com/lilith-is-all-you-need/fx_universal_loader'
SPLIT = ('fx9860-loader', 'fx9860-large-loader')


def normalized(path):
    data = path.read_bytes()
    return data if path.suffix == '.png' else data.replace(b'\r\n', b'\n')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args]).decode('utf-8')


def load_component(repo, name, repository):
    repo = Path(repo).resolve()
    if git(repo, 'status', '--porcelain'):
        raise ValueError('Commit component changes before syncing: ' + name)
    commit = git(repo, 'rev-parse', 'HEAD').strip()
    tracked = set(git(repo, 'ls-tree', '-r', '--name-only', '-z', commit).split('\0'))
    roots = [('', name == SPLIT[1])]
    if name == UNIFIED:
        roots = [('', False), ('large/', True)]

    files, paths, contents = {}, {}, {}
    for prefix, large_runtime in roots:
        manifest_name = prefix + 'source-manifest.json'
        if manifest_name not in tracked:
            raise ValueError('Missing tracked manifest: ' + manifest_name)
        manifest_path = source_file(repo, manifest_name)
        manifest = json.loads(manifest_path.read_text('utf-8'))
        entries = dict(manifest['files'])
        if large_runtime:
            entries['source-manifest.json'] = hashlib.sha256(normalized(manifest_path)).hexdigest()
        for relative, expected in entries.items():
            source = prefix + relative
            if source not in tracked:
                raise ValueError('File is absent from the pinned commit: ' + source)
            data = normalized(source_file(repo, source))
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Component manifest differs: ' + source)
            if relative in SDK_EDITION_FILES:
                continue
            if large_runtime:
                # The example keeps each build project self-contained, including
                # its vendored library and license. No extended backend is installed.
                if relative.startswith(('probes/extended-cas/', 'probes/source-guest/')):
                    if '/payload-adapter/' in relative or '/VALIDATION' in relative:
                        continue
                    if relative.endswith(('.md', '.txt', '.py')) and not relative.endswith(('CMakeLists.txt', 'relocations.py')):
                        continue
                    targets = [EXAMPLE + '/' + relative]
                elif relative in {'LICENSE', 'tests/make_source_guest.py', 'tooling/ext_profile.py'}:
                    targets = [EXAMPLE + '/' + relative]
                elif relative == 'probes/mapped-loader/vendor/fxlarge/include/fxlarge/catalog.h':
                    targets = ['probes/mapped-loader/include/fxlarge/catalog.h']
                elif relative.startswith('probes/mapped-loader/vendor/fxlarge/'):
                    continue
                elif relative.startswith(('probes/mapped-loader/', 'probes/native-loader/', 'probes/os-map-', 'profiles/')):
                    targets = [relative]
                else:
                    continue
            elif relative in {'tooling/ext_profile.py', 'tooling/hook_review.py', 'tests/test_hook_review.py', 'desktop/ProfileStudio/VALIDATION.json'}:
                continue
            else:
                targets = [relative]
            for target in targets:
                if target in files and files[target] != expected:
                    raise ValueError('Conflicting shared source: ' + target)
                files[target] = expected
                paths.setdefault(target, source)
                contents[target] = data
    return {'name': name, 'repository': repository, 'commit': commit,
            'files': dict(sorted(files.items())), 'sourcePaths': dict(sorted(paths.items()))}, contents


def sync(repositories, root=ROOT):
    lock_path = root / 'loader-components.lock.json'
    lock = json.loads(lock_path.read_text('utf-8'))
    old_components = lock['components']
    components = old_components.copy()
    if UNIFIED in repositories:
        if any(name in repositories for name in SPLIT):
            raise ValueError('Supply either a unified checkout or historical split checkouts.')
        components = [c for c in components if c['name'] not in (*SPLIT, UNIFIED)]
        components.append({'name': UNIFIED, 'repository': UNIFIED_URL})
    unknown = repositories.keys() - {c['name'] for c in components}
    if unknown:
        raise ValueError('Component absent from this lock: ' + ', '.join(sorted(unknown)))

    updates, next_components, expected_all = {}, [], {}
    for component in components:
        name = component['name']
        if name in repositories:
            component, contents = load_component(repositories[name], name, component['repository'])
            updates.update(contents)
        else:
            for relative, expected in component['files'].items():
                if hashlib.sha256(normalized(source_file(root, relative))).hexdigest() != expected:
                    raise ValueError('Existing snapshot changed: ' + relative)
        for relative, expected in component['files'].items():
            if relative in expected_all and expected_all[relative] != expected:
                raise ValueError('Conflicting snapshots: ' + relative)
            expected_all[relative] = expected
        next_components.append(component)

    previous = {rel: sha for component in old_components for rel, sha in component['files'].items()}
    for relative in (previous.keys() | updates.keys()) - SDK_EDITION_FILES:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Snapshot escapes the SDK: ' + relative)
        if path.exists():
            current = hashlib.sha256(normalized(source_file(root, relative))).hexdigest()
            if current != previous.get(relative, expected_all.get(relative)):
                raise ValueError('Local snapshot edit would be overwritten: ' + relative)
    for relative, data in updates.items():
        target = root / relative
        if target.exists() and normalized(target) == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative in previous.keys() - expected_all.keys() - SDK_EDITION_FILES:
        (root / relative).unlink(missing_ok=True)

    lock['components'] = next_components
    lock_path.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    return {'components': len(next_components), 'files': len(expected_all)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universal-loader', type=Path, help='Checkout containing both root and large/ manifests')
    parser.add_argument('--emulator', type=Path)
    parser.add_argument('--loader', type=Path, help='For historical split locks')
    parser.add_argument('--large-loader', type=Path, help='For historical split locks')
    args = parser.parse_args()
    repos = {k: v for k, v in ((UNIFIED, args.universal_loader), ('fx9860-emulator', args.emulator),
                                (SPLIT[0], args.loader), (SPLIT[1], args.large_loader)) if v}
    if not repos:
        parser.error('Provide at least one component checkout')
    print(json.dumps(sync(repos)))
