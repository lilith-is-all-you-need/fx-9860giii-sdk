"""Compile and execute the real compatibility core with deterministic hardware."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / 'compat' / 'fxlib'

class FxlibCompatTests(unittest.TestCase):
    def test_vendored_example_matches(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tooling/sync_fxlib_compat.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_legacy_aliases_are_declared_in_support_matrix(self):
        import re
        names = set(re.findall(r'^#define (\w+) fxlib_', (COMPAT / 'fxlib.h').read_text(encoding='utf-8'), re.M))
        matrix = json.loads((COMPAT / 'api.json').read_text(encoding='utf-8'))
        self.assertEqual(names, set(matrix['functions']))

    def test_real_core_semantics(self):
        compiler = os.environ.get('CC') or shutil.which('gcc') or shutil.which('clang')
        if not compiler:
            self.skipTest('A host C compiler is required for semantic execution')
        with tempfile.TemporaryDirectory(prefix='fxlib-host-') as temporary:
            exe = Path(temporary) / ('test.exe' if os.name == 'nt' else 'test')
            command = [compiler, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                       '-I', str(COMPAT), str(COMPAT / 'fxlib.c'), str(COMPAT / 'tests/host.c'), '-o', str(exe)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('semantics passed', result.stdout)

    def test_gint_backend_switches_world_for_every_file_operation(self):
        compiler = os.environ.get('CC') or shutil.which('gcc') or shutil.which('clang')
        if not compiler:
            self.skipTest('A host C compiler is required for backend execution')
        with tempfile.TemporaryDirectory(prefix='fxlib-backend-') as temporary:
            temporary = Path(temporary)
            headers = temporary / 'gint'
            headers.mkdir()
            for name in ('display', 'keyboard', 'clock', 'rtc', 'gint', 'bfile', 'hardware'):
                (headers / (name + '.h')).write_text('#include "fake_gint.h"\n')
            exe = temporary / ('test.exe' if os.name == 'nt' else 'test')
            command = [compiler, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                       '-I', str(temporary), '-I', str(COMPAT), '-I', str(COMPAT / 'tests'),
                       str(COMPAT / 'fxlib_gint.c'), str(COMPAT / 'tests/backend.c'), '-o', str(exe)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('backend passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
