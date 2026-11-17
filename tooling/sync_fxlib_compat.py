"""Synchronize the self-contained legacy example with the canonical MIT layer."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'compat' / 'fxlib'
TARGET = ROOT / 'examples' / 'legacy-fxlib' / 'compat' / 'fxlib'

def sync(check: bool = False) -> list[str]:
    expected = {p.relative_to(SOURCE): p for p in SOURCE.rglob('*')
                if p.is_file() and not any(x in ('tests', '__pycache__') for x in p.relative_to(SOURCE).parts)}
    actual = {p.relative_to(TARGET): p for p in TARGET.rglob('*') if p.is_file()} if TARGET.exists() else {}
    problems = []
    for relative, source in expected.items():
        target = TARGET / relative
        if not target.exists() or target.read_bytes() != source.read_bytes():
            problems.append(str(relative))
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    extras = sorted(set(actual) - set(expected))
    if extras:
        # A contributor may have added a file; never delete it implicitly.
        raise RuntimeError('Unexpected vendored files (not removed): ' + ', '.join(map(str, extras)))
    if check and problems:
        raise RuntimeError('Run tooling/sync_fxlib_compat.py; differing files: ' + ', '.join(problems))
    return problems

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changes = sync(args.check)
    print('fxlib compatibility example is synchronized' if not changes else f'Synchronized {len(changes)} files')

if __name__ == '__main__':
    main()
