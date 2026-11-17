"""Shared, explicit offline package inventory. Never copy user games or ROMs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

LOADER_FILES = (
    'tooling/loader_suite.py',
    'profiles/registry.json',
    'probes/native-loader/tools/prepare.py',
    'probes/storage-loader/tools/prepare.py',
    'probes/mapped-loader/tools/prepare.py',
    'loader-components.lock.json',
)
LOADER_BINARIES = ('FlashLd.g1a', 'Loader.g1a', 'KLoad.g1a', 'KhiMap.g1a')
DEVELOPMENT_FILES = ('tooling/legacy_project.py', 'tooling/project_assets.py')
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
    expected = record.get('files', {})
    checked = {}
    for name in LOADER_BINARIES:
        actual = digest(source_file(artifacts, name))
        if expected.get(name) != actual:
            raise ValueError('Loader build manifest missing or mismatching ' + name)
        checked[name] = actual
    return checked


def copy_loader_runtime(root, artifacts, output):
    """Copy the complete default Flash path and all supported Loader backends."""
    root, output = Path(root), Path(output)
    # Validate all inputs before creating any output.
    for relative in LOADER_FILES:
        source_file(root, relative)
    hashes = loader_artifact_hashes(artifacts)
    for relative in LOADER_FILES:
        copy_file(root, output, relative)
    target = output / 'loader-artifacts'
    target.mkdir(parents=True, exist_ok=True)
    for name in LOADER_BINARIES:
        shutil.copy2(Path(artifacts) / name, target / name)
    # Rebuild the inventory from the allowlist. Extra files/records may be private.
    (target / 'manifest.json').write_text(json.dumps({'files': hashes}, indent=2) + '\n', encoding='utf-8')


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


def public_component_sources(root):
    """Use the reviewed source snapshot inventory, never a recursive probes copy."""
    root = Path(root)
    lock = json.loads(source_file(root, 'loader-components.lock.json').read_text(encoding='utf-8-sig'))
    paths = {'loader-components.lock.json'}
    for component in lock['components']:
        for relative in component['files']:
            if Path(relative).suffix.lower() in {'.g1a', '.g3a', '.bin', '.rom', '.elf', '.exe', '.dll', '.zip'}:
                raise ValueError('Compiled/private input is not public source: ' + relative)
            source_file(root, relative)
            paths.add(relative)
    return sorted(paths)
