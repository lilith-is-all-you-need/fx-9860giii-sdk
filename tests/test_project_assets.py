"""Resource import contracts; optional actual native build with FXSTUDIO_TEST_NATIVE=1."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_assets', ROOT / 'tooling/project_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def png(width=9, height=2):
    image = Image.new('RGBA', (width, height), 'white')
    for x in range(0, width, 2):
        image.putpixel((x, 0), (0, 0, 0, 255))
    image.putpixel((0, height - 1), (0, 0, 0, 0))
    image.putpixel((width - 1, height - 1), (0, 0, 0, 255))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fx 资源 ' ")
        self.root = Path(self.temp.name)
        self.project = self.root / '工程'
        self.project.mkdir()
        self.cmake = b'cmake_minimum_required(VERSION 3.15)\r\nproject(test C)\r\nadd_executable(app main.c)\r\n'
        (self.project / 'CMakeLists.txt').write_bytes(self.cmake)
        (self.project / 'main.c').write_text('int main(void) { return 0; }\n')
        self.input = self.root / '中文 图片.png'
        self.input.write_bytes(png())

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}

    def test_packed_bitmap_transparency_and_nonbyte_width(self):
        data, width, height, stride = assets.convert_bitmap(self.input.read_bytes())
        self.assertEqual((width, height, stride), (9, 2, 2))
        self.assertEqual(data, b'\xaa\x80\x00\x80')
        with self.assertRaises(ValueError):
            assets.convert_bitmap(self.input.read_bytes(), 256)

    def test_import_and_idempotency_preserve_original_cmake(self):
        result = assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(result['target'], 'app')
        self.assertTrue((self.project / 'CMakeLists.txt').read_bytes().startswith(self.cmake))
        header = (self.project / assets.HEADER).read_text(encoding='utf-8')
        self.assertIn('#define logo_stride 2u', header)
        before = self.snapshot()
        repeat = assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertTrue(repeat['unchanged'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(assets.list_assets(self.project)['assets'][0]['symbol'], 'logo')

    def test_conflicts_do_not_modify_existing_files(self):
        assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.input.write_bytes(png(8, 2))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'different'):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(before, self.snapshot())
        (self.project / assets.HEADER).write_text('user edited')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'edited'):
            assets.import_asset(self.project, self.input, 'bitmap', 'another')
        self.assertEqual(before, self.snapshot())

    def test_dry_run_and_invalid_inputs_leave_no_outputs(self):
        before = self.snapshot()
        result = assets.import_asset(self.project, self.input, 'bitmap', 'logo', dry_run=True)
        self.assertTrue(result['dryRun'])
        self.assertEqual(before, self.snapshot())
        for symbol in ('../bad', 'int', 'bad-name', '_reserved', '1name'):
            with self.assertRaises(ValueError):
                assets.import_asset(self.project, self.input, 'bitmap', symbol)
        with self.assertRaises(ValueError):
            assets.import_asset(self.project, self.input, 'font', 'font')
        self.assertEqual(before, self.snapshot())

    def test_target_selection_ignores_comments_and_requires_ambiguity_resolution(self):
        with (self.project / 'CMakeLists.txt').open('a') as file:
            file.write('# add_executable(fake fake.c)\n#[[add_executable(fake2 fake.c)]]\nadd_executable(second main.c)\nadd_executable(alias ALIAS app)\n')
        self.assertEqual(assets.project_targets(self.project), ['app', 'second'])
        with self.assertRaisesRegex(ValueError, '--target'):
            assets.import_asset(self.project, self.input, 'image', 'picture')
        result = assets.import_asset(self.project, self.input, 'image', 'picture', target='second')
        self.assertEqual(result['target'], 'second')
        self.assertIn('type: bopti-image', (self.project / 'assets/fxstudio/picture/fxconv-metadata.txt').read_text(encoding='utf-8'))

    def test_user_files_symbols_and_include_block_are_protected(self):
        (self.project / 'main.c').write_text('const unsigned char logo[] = {1};\n')
        with self.assertRaisesRegex(ValueError, 'already defined'):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        (self.project / 'main.c').write_text('int main(void) {return 0;}')
        user_file = self.project / assets.HEADER
        user_file.parent.mkdir(parents=True)
        user_file.write_text('important user header')
        with self.assertRaisesRegex(ValueError, 'user file'):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(user_file.read_text(encoding='utf-8'), 'important user header')

    def test_symbol_scanner_ignores_references_comments_and_strings(self):
        (self.project / 'main.c').write_text('''/* unsigned char blob[3] = {1}; */
const char *example = "unsigned char blob[3];";
extern const unsigned char blob[];
int main(void) { return blob[1]==0x42; }
''')
        binary = self.root / 'payload.bin'
        binary.write_bytes(b'ABC')
        assets.import_asset(self.project, binary, 'binary', 'blob')
        self.assertTrue((self.project / 'assets/fxstudio/blob/data.c').is_file())

    def test_uninitialized_array_and_cpp_keywords_are_rejected(self):
        (self.project / 'main.c').write_text('unsigned char logo[1];\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'already defined'):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        for keyword in ('operator', 'constexpr', 'co_await', 'alignas', 'reinterpret_cast'):
            with self.assertRaises(ValueError):
                assets.import_asset(self.project, self.input, 'bitmap', keyword)
        self.assertEqual(before, self.snapshot())

    def test_external_edits_before_commit_survive(self):
        commit = assets._commit
        cmake = self.project / 'CMakeLists.txt'
        external = self.cmake + b'# external editor change\n'
        def change_cmake(project, outputs, expected):
            cmake.write_bytes(external)
            return commit(project, outputs, expected)
        with mock.patch.object(assets, '_commit', side_effect=change_cmake):
            with self.assertRaisesRegex(ValueError, 'changed during import'):
                assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(cmake.read_bytes(), external)
        self.assertFalse((self.project / assets.HEADER).exists())
        assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        header = self.project / assets.HEADER
        def change_header(project, outputs, expected):
            header.write_text('external header edit')
            return commit(project, outputs, expected)
        with mock.patch.object(assets, '_commit', side_effect=change_header):
            with self.assertRaisesRegex(ValueError, 'changed during import'):
                assets.import_asset(self.project, self.input, 'image', 'picture')
        self.assertEqual(header.read_text(encoding='utf-8'), 'external header edit')
        self.assertFalse((self.project / 'assets/fxstudio/picture').exists())

    def test_static_false_and_dynamic_cmake_conditions(self):
        cmake = self.project / 'CMakeLists.txt'
        cmake.write_text('project(test C)\nif(FALSE)\nadd_executable(ghost main.c)\nelse()\nadd_executable(real main.c)\nendif()\n')
        self.assertEqual(assets.project_targets(self.project), ['real'])
        result = assets.import_asset(self.project, self.input, 'bitmap', 'logo', dry_run=True)
        self.assertEqual(result['target'], 'real')
        cmake.write_text('project(test C)\nif(ENABLE_APP)\nadd_executable(app main.c)\nendif()\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'dynamic CMake'):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(before, self.snapshot())
        cmake.write_text('project(test C)\nfunction(make_app)\nadd_executable(ghost main.c)\nendfunction()\n')
        with self.assertRaisesRegex(ValueError, 'dynamic CMake'):
            assets.project_targets(self.project)

    def test_manifest_traversal_and_linked_destinations_are_rejected(self):
        folder = self.project / assets.ASSET_DIR
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'assets': [], 'files': {'../../outside': 'x'}}))
        with self.assertRaises(ValueError):
            assets.list_assets(self.project)
        (folder / 'manifest.json').unlink()
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (folder / 'logo').symlink_to(outside, target_is_directory=True)
        except OSError:
            return  # Windows hosts may not grant symbolic-link creation.
        with self.assertRaises(ValueError):
            assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        self.assertEqual(list(outside.iterdir()), [])

    def test_subdirectory_target_and_manifest_validation(self):
        (self.project / 'CMakeLists.txt').write_text('project(test C)\nadd_subdirectory(src)\n')
        folder = self.project / 'src'
        folder.mkdir()
        (folder / 'CMakeLists.txt').write_text('add_executable(${PROJECT_NAME} main.c)\n')
        (folder / 'main.c').write_text('int main(void) {return 0;}')
        self.assertEqual(assets.project_targets(self.project), ['test'])
        assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        path = self.project / assets.MANIFEST
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['assets'][0]['target'] = 'target)\nmessage(FATAL_ERROR inject)'
        path.write_text(json.dumps(manifest))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Invalid resource'):
            assets.import_asset(self.project, self.input, 'image', 'picture')
        self.assertEqual(before, self.snapshot())

    def test_binary_and_font_metadata_are_complete(self):
        binary = self.root / 'data.bin'
        binary.write_bytes(bytes(range(256)))
        assets.import_asset(self.project, binary, 'binary', 'payload')
        self.input.write_bytes(png(30, 5))
        assets.import_asset(self.project, self.input, 'font', 'digits', font_grid='3x5')
        metadata = (self.project / 'assets/fxstudio/digits/fxconv-metadata.txt').read_text(encoding='utf-8')
        self.assertIn('charset: numeric', metadata)
        self.assertIn('grid.size: 3x5', metadata)
        header = (self.project / assets.HEADER).read_text(encoding='utf-8')
        self.assertIn('extern const font_t digits;', header)
        self.assertIn('payload[256]', header)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            assets.import_asset(self.project, binary, 'binary', 'payload_size')
        self.assertEqual(before, self.snapshot())

    def test_cli_returns_utf8_json(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/project_assets.py'), 'import', '--project', str(self.project),
                               '--input', str(self.input), '--kind', 'bitmap', '--symbol', 'logo', '--dry-run'],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['project'], str(self.project))

    @unittest.skipUnless(os.environ.get('FXSTUDIO_TEST_NATIVE') == '1', 'set FXSTUDIO_TEST_NATIVE=1 for actual offline SuperH build')
    def test_generated_resources_compile_and_link_with_native_sdk(self):
        sdk = Path(os.environ.get('FXSTUDIO_TEST_SDK', ROOT / 'dist-toolchain/native-sdk'))
        (self.project / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.15)
project(ResourceNative C)
include(GenerateG1A)
find_package(Gint 2.9 REQUIRED)
add_executable(app main.c)
target_link_libraries(app Gint::Gint)
generate_g1a(TARGET app OUTPUT "assets.g1a" NAME "ASSETS" INTERNAL "@ASSETS")
''')
        assets.import_asset(self.project, self.input, 'bitmap', 'logo')
        assets.import_asset(self.project, self.input, 'image', 'picture')
        binary = self.root / 'data.bin'
        binary.write_bytes(b'abc')
        assets.import_asset(self.project, binary, 'binary', 'payload')
        self.input.write_bytes(png(30, 5))
        assets.import_asset(self.project, self.input, 'font', 'digits', font_grid='3x5')
        (self.project / 'main.c').write_text('''#include <gint/display.h>
#include <project_assets.h>
volatile unsigned result;
int main(void) { dclear(C_WHITE); dimage(0,0,&picture); dfont(&digits);
result=logo[0]+payload[0]+logo_width+logo_height+logo_stride+payload_size;
dupdate(); return 0; }
''')
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/build-native.py'), str(sdk), str(self.project),
                               str(self.root / 'native-output'), 'Debug'], capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((self.root / 'native-output/artifact.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(manifest['g1a']).is_file())
        # The supplied C++ template does not enable C. Importing generated C
        # arrays must still compile them, and declarations must retain C linkage.
        (self.project / 'main.c').rename(self.project / 'main.cpp')
        cmake = self.project / 'CMakeLists.txt'
        cmake.write_text(cmake.read_text(encoding='utf-8').replace('project(ResourceNative C)', 'project(ResourceNative CXX)')
                         .replace('app main.c)', 'app main.cpp)').replace('app Gint::Gint)', 'app stdc++ Gint::Gint)'))
        proc = subprocess.run([sys.executable, str(ROOT / 'tooling/build-native.py'), str(sdk), str(self.project),
                               str(self.root / 'native-cpp-output'), 'Debug'], capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((self.root / 'native-cpp-output/artifact.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(manifest['g1a']).is_file())


if __name__ == '__main__':
    unittest.main()
