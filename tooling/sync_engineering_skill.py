"""Synchronize maintained scaffolds into the portable skill, or check for drift.

Only generated assets/scaffolds files are managed. --check never writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scaffolds'
TARGET = ROOT / 'skills/fxstudio/assets/scaffolds'
MANIFEST = TARGET.parent / 'scaffolds-manifest.json'


def inventory(root):
    result = {}
    if root.is_symlink() or getattr(root, 'is_junction', lambda: False)():
        raise RuntimeError('Template root cannot be a directory alias')
    for path in root.rglob('*') if root.exists() else ():
        relative = path.relative_to(root)
        if any(part in {'.fxstudio', '.git', '__pycache__'} or part.startswith('build') for part in relative.parts):
            continue
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise RuntimeError('Template aliases are not supported: ' + str(path))
        if not path.is_file():
            continue
        if root == SOURCE:
            if relative.parts[0] not in {'guarded-c', 'evidence-session'}:
                continue
            if path.suffix.lower() not in {'.c', '.h', '.cpp', '.hpp', '.md', '.txt', '.json', '.png', '.cmake'} and path.name != 'LICENSE':
                continue
        result[relative.as_posix()] = path
    return result


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync(check=False):
    expected, actual = inventory(SOURCE), inventory(TARGET)
    if not expected:
        raise RuntimeError('Scaffold source missing')
    extra = sorted(actual.keys() - expected.keys())
    if extra:
        raise RuntimeError('Unmanaged extra files; inspect instead of deleting: ' + repr(extra))
    differences = [name for name, source in expected.items()
                   if name not in actual or checksum(source) != checksum(actual[name])]
    rows = [{'path': name, 'bytes': p.stat().st_size, 'sha256': checksum(p)}
            for name, p in sorted(expected.items())]
    manifest = {'schemaVersion': 1, 'source': 'scaffolds/', 'files': rows}
    same_manifest = MANIFEST.exists() and json.loads(MANIFEST.read_text(encoding='utf8')) == manifest
    if check and (differences or not same_manifest):
        raise RuntimeError('Skill scaffold copy differs: ' + repr(differences))
    if not check:
        for name in differences:
            destination = TARGET / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(expected[name], destination)
        MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8', newline='\n')
    return {'ok': True, 'files': len(expected), 'mode': 'check' if check else 'sync'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(sync(args.check), indent=2))
