"""Portable engineering helpers; no SDK download, compiler or Agent startup.

JSON output. Exit 0: requested check succeeded; 2: mismatch/budget failure;
1: invalid input or operational error. Writes always require new paths.
Budget checks measure bytes, not ELF/G1A pairing or hardware compatibility.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys

SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.inc', '.s',
                   '.ld', '.cmake', '.py', '.ps1', '.sh', '.json', '.toml',
                   '.yaml', '.yml', '.txt', '.md', '.png', '.svg', '.fxconv'}
SKIP_DIRS = {'.git', '.fxstudio', '.fxide-source', '.vs', '__pycache__',
             'node_modules', 'bin', 'obj', 'results', 'dist', 'CMakeFiles'}
SKIP_NAMES = {'project.fxide.json', 'artifact.json', 'bridge.json',
              'CMakeCache.txt', 'compile_commands.json', 'builder-key',
              'known_hosts', 'id_rsa', 'id_ed25519'}
TEMPLATES = Path(__file__).resolve().parents[1] / 'assets/scaffolds'


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def new_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def alias(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def files(root, omitted=()):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Project root must be a directory')
    omitted = {Path(p).resolve() for p in omitted}
    result = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not fnmatch.fnmatch(d.lower(), 'build*'))
        for name in dirs:
            if alias(parent / name):
                raise ValueError('Directory symlink/junction is not an input snapshot: ' + str(parent / name))
        for name in sorted(names):
            path = parent / name
            if name in SKIP_NAMES or name.startswith('.env') or path.suffix.lower() not in SOURCE_SUFFIXES and name not in {'Makefile', 'LICENSE', '.gitattributes', '.gitignore'}:
                continue
            if alias(path):
                raise ValueError('Source symlinks must be resolved explicitly: ' + str(path))
            if path.resolve() in omitted:
                continue
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError('Source input exceeds 64 MiB inspection bound: ' + str(path))
            result.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)})
    if not result:
        raise ValueError('No source inputs selected; refusing an empty success')
    return sorted(result, key=lambda item: item['path'])


def snapshot(root, output):
    root = root.resolve(strict=True)
    result = {'schemaVersion': 1, 'kind': 'source-snapshot',
              'scope': 'source-text-and-assets-v1', 'createdUtc': stamp(),
              'rootName': root.name, 'files': files(root, [output]),
              'excludes': {'directories': sorted(SKIP_DIRS), 'patterns': ['build*', '.env*'],
                           'names': sorted(SKIP_NAMES)},
              'note': 'Hashes selected inputs, not dependencies/toolchain or a full backup.'}
    new_json(output, result)
    return {'ok': True, 'snapshot': str(output.resolve()), 'files': len(result['files'])}


def compare(root, snapshot_path):
    baseline = read_json(snapshot_path)
    if baseline.get('schemaVersion') != 1 or baseline.get('kind') != 'source-snapshot' or baseline.get('scope') != 'source-text-and-assets-v1':
        raise ValueError('Unsupported snapshot schema or scope')
    expected = {}
    for item in baseline['files']:
        path = PurePosixPath(item['path'])
        if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in item['path'] or ':' in item['path']:
            raise ValueError('Unsafe snapshot member path')
        if item['path'] in expected:
            raise ValueError('Duplicate snapshot member')
        expected[item['path']] = item
    if not expected:
        raise ValueError('Empty snapshot is not a verified baseline')
    actual = {item['path']: item for item in files(root, [snapshot_path])}
    added = sorted(actual.keys() - expected.keys())
    removed = sorted(expected.keys() - actual.keys())
    changed = sorted(key for key in actual.keys() & expected.keys() if actual[key] != expected[key])
    return {'ok': not (added or removed or changed), 'added': added, 'removed': removed,
            'changed': changed, 'filesCompared': len(actual),
            'note': 'Reports differences only; no files were restored or changed.'}


def scaffold(name, destination):
    source = TEMPLATES / name
    if name not in {'guarded-c', 'evidence-session'} or not source.is_dir():
        raise ValueError('Unknown or unbundled scaffold')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination already exists; refusing to merge or overwrite')
    for path in source.rglob('*'):
        if alias(path):
            raise ValueError('Template contains a symlink or junction')
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('Destination cannot be inside its template')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return {'ok': True, 'project': str(destination.resolve()), 'template': name,
            'next': 'Review README, then use the normal Fx Studio build workflow.'}


def budget(artifact, policy_path, output):
    policy = read_json(policy_path)
    ceiling = policy.get('maxG1aBytes')
    reserve = policy.get('reserveBytes', 0)
    if policy.get('schemaVersion') != 1 or type(ceiling) is not int or ceiling <= 512 or type(reserve) is not int or not 0 <= reserve < ceiling:
        raise ValueError('Policy requires schemaVersion 1 and positive byte budgets')
    if not isinstance(policy.get('basis'), str) or not policy['basis'].strip() or policy.get('kind') != 'project-policy':
        raise ValueError('Policy must identify its basis; it is not a discovered OS limit')
    size = artifact.stat().st_size
    if size <= 512 or artifact.suffix.lower() != '.g1a':
        raise ValueError('Expected a nonempty G1A candidate; SDK must validate header/payload')
    result = {'schemaVersion': 1, 'ok': size <= ceiling - reserve, 'kind': 'artifact-byte-budget',
              'artifact': {'name': artifact.name, 'bytes': size, 'sha256': sha(artifact)},
              'policy': policy, 'usableBudgetBytes': ceiling - reserve,
              'remainingBytes': ceiling - reserve - size,
              'pairingAndStructure': 'not_checked_use_sdk_build_verifier',
              'hardware': 'not_tested', 'createdUtc': stamp()}
    if output:
        new_json(output, result)
    return result


def hardware_record(artifact, output):
    if not artifact.is_file() or artifact.suffix.lower() != '.g1a' or artifact.stat().st_size <= 512:
        raise ValueError('Choose the actual nonempty G1A candidate')
    data = read_json(TEMPLATES / 'evidence-session/hardware-results.template.json')
    data['artifact'] = {'name': artifact.name, 'bytes': artifact.stat().st_size, 'sha256': sha(artifact)}
    data['createdUtc'] = stamp()
    new_json(output, data)
    return {'ok': True, 'record': str(output.resolve()), 'hardware': 'not_tested',
            'note': 'All observations remain not_run; fill only from actual device observations.'}


def main(argv=None):
    # Windows redirected streams may default to an ANSI code page. JSON is UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('new')
    new.add_argument('template', choices=('guarded-c', 'evidence-session'))
    new.add_argument('destination', type=Path)
    snap = commands.add_parser('snapshot')
    snap.add_argument('project', type=Path)
    snap.add_argument('--output', type=Path, required=True)
    diff = commands.add_parser('compare')
    diff.add_argument('project', type=Path)
    diff.add_argument('--snapshot', type=Path, required=True)
    measure = commands.add_parser('budget')
    measure.add_argument('artifact', type=Path)
    measure.add_argument('--policy', type=Path, required=True)
    measure.add_argument('--output', type=Path)
    record = commands.add_parser('hardware-record')
    record.add_argument('artifact', type=Path)
    record.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'new':
            result = scaffold(args.template, args.destination)
        elif args.command == 'snapshot':
            result = snapshot(args.project, args.output)
        elif args.command == 'compare':
            result = compare(args.project, args.snapshot)
        elif args.command == 'budget':
            result = budget(args.artifact, args.policy, args.output)
        else:
            result = hardware_record(args.artifact, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
