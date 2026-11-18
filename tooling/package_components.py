"""Shared, explicit offline package inventory. Never copy user games or ROMs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

LOADER_FILES = (
    'tooling/loader_suite.py',
    'tooling/profile_job.py',
    'tooling/bundle_v2.py',
    'tooling/ghidra/ExportG1aEvidence.java',
    'tooling/ghidra/PrepareG1a.java',
    'tooling/ghidra/log4j.xml',
    'profiles/registry.json',
    'probes/native-loader/tools/prepare.py',
    'probes/storage-loader/tools/prepare.py',
    'probes/mapped-loader/tools/prepare.py',
    'loader-components.lock.json',
)
LOADER_BINARIES = ('FlashLd.g1a',)
# These product entry points belong to the SDK. Upstream also ships a
# standalone edition whose input policy differs.
SDK_EDITION_FILES = frozenset({
    'tooling/loader_suite.py', 'tooling/profile_job.py', 'tooling/bundle_v2.py',
    'tooling/package_profile_studio.py', 'profiles/registry.json',
    'desktop/ProfileStudio/MainWindow.xaml', 'desktop/ProfileStudio/MainWindow.xaml.cs', 'desktop/ProfileStudio/Models.cs',
    'desktop/ProfileStudio/README.en.md', 'desktop/ProfileStudio/README.zh-CN.md',
    'tests/test_loader_suite.py', 'tests/test_profile_job.py', 'probes/mapped-loader/CMakeLists.txt',
})
EXAMPLE = 'sdk/examples/oversized-loader'
DEVELOPMENT_FILES = ('tooling/package_components.py', 'tooling/legacy_project.py', 'tooling/project_assets.py',
                     'tooling/build-project.py', 'tooling/native-sdk/README.md',
                     'tooling/native-fxsdk/README.md', 'source-notices/README.md',
                     EXAMPLE + '/README.en.md', EXAMPLE + '/README.zh-CN.md')
DEVELOPMENT_TREES = ('compat/fxlib', 'examples/legacy-fxlib')
IGNORED = {'.git', '.fxstudio', '__pycache__', 'bin', 'obj'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_file(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Required regular package input missing or outside root: ' + str(path))
    return path


def copy_file(root, output, relative):
    source = source_file(root, relative)
    target = Path(output) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def loader_artifact_hashes(artifacts):
    artifacts = Path(artifacts)
    record = json.loads(source_file(artifacts, 'manifest.json').read_text(encoding='utf-8-sig'))
    if record.get('schemaVersion') != 2 or record.get('bundleFormat') != 2:
        raise ValueError('Loader Suite 0.2 requires schemaVersion 2 / bundleFormat 2 artifacts')
    expected = record.get('files', {})
    checked = {}
    for name in LOADER_BINARIES:
        actual = digest(source_file(artifacts, name))
        if expected.get(name) != actual:
            raise ValueError('Loader build manifest missing or mismatching ' + name)
        checked[name] = actual
    return checked


def copy_loader_runtime(root, artifacts, output):
    """Copy the V2 runtime and its hash-pinned public component sources."""
    root, output = Path(root), Path(output)
    # Validate all inputs before creating any output.
    for relative in set(LOADER_FILES) | SDK_EDITION_FILES:
        source_file(root, relative)
    public_sources = public_component_sources(root, verify=True)
    if not set(LOADER_FILES) <= set(public_sources) | SDK_EDITION_FILES:
        raise ValueError('Loader runtime dependencies are absent from the public component lock')
    hashes = loader_artifact_hashes(artifacts)
    for relative in sorted(set(public_sources) | SDK_EDITION_FILES):
        copy_file(root, output, relative)
    target = output / 'loader-artifacts'
    target.mkdir(parents=True, exist_ok=True)
    for name in LOADER_BINARIES:
        shutil.copy2(Path(artifacts) / name, target / name)
    # Rebuild the inventory from the allowlist. Extra files/records may be private.
    (target / 'manifest.json').write_text(json.dumps({'schemaVersion': 2, 'bundleFormat': 2, 'files': hashes}, indent=2) + '\n', encoding='utf-8')


def development_inventory(root):
    root = Path(root)
    paths = list(DEVELOPMENT_FILES)
    for relative in DEVELOPMENT_TREES:
        folder = root / relative
        if not folder.is_dir():
            raise ValueError('Missing development resource: ' + str(folder))
        for path in sorted(folder.rglob('*')):
            parts = path.relative_to(folder).parts
            if any(p in IGNORED or p.startswith('build') for p in parts[:-1]):
                continue
            if path.is_file() and path.suffix.lower() not in {'.pyc', '.g1a', '.elf', '.o', '.exe'}:
                paths.append(path.relative_to(root).as_posix())
    for path in paths:
        source_file(root, path)
    return paths


def copy_development_runtime(root, output):
    for relative in development_inventory(root):
        copy_file(root, output, relative)


def public_component_sources(root, verify=False):
    """Use the reviewed source snapshot inventory, never a recursive probes copy."""
    root = Path(root)
    lock = json.loads(source_file(root, 'loader-components.lock.json').read_text(encoding='utf-8-sig'))
    paths = {'loader-components.lock.json'}
    seen = {}
    for component in lock['components']:
        for relative, expected in component['files'].items():
            if Path(relative).suffix.lower() in {'.g1a', '.g3a', '.bin', '.rom', '.elf', '.exe', '.dll', '.zip'}:
                raise ValueError('Compiled/private input is not public source: ' + relative)
            source = source_file(root, relative)
            if relative in seen and seen[relative] != expected:
                raise ValueError('Conflicting public component source: ' + relative)
            seen[relative] = expected
            if verify:
                data = source.read_bytes()
                if source.suffix != '.png':
                    data = data.replace(b'\r\n', b'\n')
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError('Component differs from its public source lock: ' + relative)
            paths.add(relative)
    return sorted(paths)
