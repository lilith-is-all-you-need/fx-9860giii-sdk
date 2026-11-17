"""Compile/run the portable scratch/rollback contracts with a host C compiler."""
from pathlib import Path
import argparse
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    args = parser.parse_args()
    source = ROOT / 'scaffolds/guarded-c'
    with tempfile.TemporaryDirectory(prefix='fx-guard-host-') as temporary:
        binary = Path(temporary) / 'guard-contract.exe'
        command = [args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   str(source / 'src/fx_arena.c'), str(source / 'src/model.c'),
                   str(source / 'src/contract.c'), str(source / 'tests/host_main.c'),
                   '-o', str(binary)]
        subprocess.run(command, check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)
        print(json.dumps({'ok': True, 'scope': 'host C scratch/rollback contracts',
                          'targetHardwareVerified': False}))


if __name__ == '__main__':
    main()
