"""Legacy migration contract tests; originals and existing output remain intact."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_project', ROOT / 'tooling/legacy_project.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class LegacyProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fx 迁移 ' ")
        self.root = Path(self.temp.name)
        self.source = self.root / '旧工程'
        self.source.mkdir()
        self.raw = b'#include "fxlib.h"\r\nint AddIn_main(int a,unsigned short b) {Bdisp_AllClr_VRAM();return 0;}\r\n'
        (self.source / 'old.c').write_bytes(self.raw)
        (self.source / 'fxlib.h').write_text('official header must not be copied')
        (self.source / 'sprites.h').write_text('static const unsigned char sprite[]={0x80};\n')
        (self.source / 'picture.bin').write_bytes(b'\x00\x01')
        (self.source / 'INIT').mkdir()
        (self.source / 'INIT/crt0.c').write_text('old startup')
        (self.source / 'old.lib').write_bytes(b'old binary library')
        self.output = self.root / '新工程'

    def tearDown(self):
        self.temp.cleanup()

    def test_copies_sources_unchanged_and_vendors_portable_wrapper(self):
        result = legacy.create_project(self.source, self.output, '迁移示例')
        self.assertEqual((self.source / 'old.c').read_bytes(), self.raw)
        self.assertEqual((self.output / 'legacy/old.c').read_bytes(), self.raw)
        self.assertFalse((self.output / 'legacy/fxlib.h').exists())
        self.assertFalse((self.output / 'legacy/old.lib').exists())
        self.assertFalse((self.output / 'legacy/INIT').exists())
        self.assertTrue((self.output / 'compat/fxlib/fxlib.h').is_file())
        cmake = (self.output / 'CMakeLists.txt').read_text(encoding='utf-8')
        self.assertIn('Fxlib::Compat', cmake)
        self.assertIn('compat/fxlib/fxlib_entry.c', cmake)
        self.assertNotIn(str(ROOT), cmake)
        self.assertFalse(result['hardwareTested'])
        self.assertEqual(result['sources'], ['legacy/old.c'])
        self.assertTrue((self.output / 'MIGRATION.txt').is_file())

    def test_single_file_import_includes_headers_resources_not_other_units(self):
        (self.source / 'other.c').write_text('int main(void) {return 0;}')
        (self.source / 'unrelated.json').write_text('{"private":"leave behind"}')
        result = legacy.create_project(self.source / 'old.c', self.output, 'Single')
        self.assertEqual(result['sources'], ['legacy/old.c'])
        self.assertTrue((self.output / 'legacy/sprites.h').is_file())
        self.assertTrue((self.output / 'legacy/picture.bin').is_file())
        self.assertFalse((self.output / 'legacy/other.c').exists())
        self.assertFalse((self.output / 'legacy/unrelated.json').exists())

    def test_refuses_existing_or_nested_output_and_dry_run_is_readonly(self):
        report = legacy.create_project(self.source, self.output, dry_run=True)
        self.assertTrue(report['dryRun'])
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            legacy.create_project(self.source, self.source / 'new')
        self.output.mkdir()
        file = self.output / 'important.txt'
        file.write_text('keep')
        with self.assertRaises(ValueError):
            legacy.create_project(self.source, self.output)
        self.assertEqual(file.read_text(encoding='utf-8'), 'keep')

    def test_reports_uncovered_api_shc_assembly_and_nonutf8(self):
        source = self.raw + b'\n#pragma section _TOP\nvoid extra(void) {Bdisp_NotAnApi(); __asm__("nop");}\n//\xff\n'
        (self.source / 'old.c').write_bytes(source)
        result = legacy.create_project(self.source, self.output)
        kinds = {x['kind'] for x in result['warnings']}
        self.assertTrue({'unsupported-api', 'shc-pragma', 'assembly-or-syscall', 'encoding'} <= kinds)
        self.assertEqual((self.output / 'legacy/old.c').read_bytes(), source)
        self.assertEqual(result['status'], 'needs-review')

    def test_existing_main_is_not_given_a_second_entry(self):
        (self.source / 'old.c').write_text('#include "fxlib.h"\nint main(void){return 0;}')
        result = legacy.create_project(self.source, self.output)
        self.assertFalse(result['entryAdapter'])
        self.assertNotIn('compat/fxlib/fxlib_entry.c', (self.output / 'CMakeLists.txt').read_text(encoding='utf-8'))
        self.assertTrue(any('fxlib_compat_init' in x['message'] for x in result['warnings']))

    def test_cli_prints_utf8_report(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/legacy_project.py'), 'create', '--source', str(self.source),
                               '--output', str(self.output), '--name', '中文工程', '--dry-run'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['name'], '中文工程')

    def test_assembly_files_and_oversized_single_file_scope(self):
        (self.source / 'module.src').write_text('MOV #1,R0')
        report = legacy.create_project(self.source, self.output, dry_run=True)
        self.assertTrue(any(x['kind'] == 'assembly-file' for x in report['warnings']))
        large = self.source / 'large.bin'
        with large.open('wb') as file:
            file.truncate(65 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, 'too broad'):
            legacy.create_project(self.source / 'old.c', self.output)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get('FXSTUDIO_TEST_NATIVE') == '1', 'set FXSTUDIO_TEST_NATIVE=1 for actual offline SuperH build')
    def test_migrated_addin_compiles_and_links(self):
        legacy.create_project(self.source, self.output, 'Migrated')
        sdk = Path(os.environ.get('FXSTUDIO_TEST_SDK', ROOT / 'dist-toolchain/native-sdk'))
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/build-native.py'), str(sdk), str(self.output),
                               str(self.root / 'native-output'), 'Debug'], capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((self.root / 'native-output/artifact.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(manifest['g1a']).is_file())
        (self.source / 'old.c').rename(self.source / 'old.cpp')
        cpp_output = self.root / 'cpp-project'
        legacy.create_project(self.source, cpp_output, 'MigratedCpp')
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/build-native.py'), str(sdk), str(cpp_output),
                               str(self.root / 'native-cpp-output'), 'Debug'], capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((self.root / 'native-cpp-output/artifact.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(manifest['g1a']).is_file())


if __name__ == '__main__':
    unittest.main()
