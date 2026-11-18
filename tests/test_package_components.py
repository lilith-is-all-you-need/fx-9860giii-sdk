"""Exercise assembled directories without relying on checkout-relative imports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tooling'))
from assemble_loader_suite import inherited_file
import package_components as packages
import check_emulator_build as freshness


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Fx package ' ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir()
        hashes = {}
        for name in packages.LOADER_BINARIES:
            data = ('Authored test launcher ' + name).encode()
            (self.artifacts / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (self.artifacts / 'private-game.g1a').write_bytes(b'never redistribute')
        hashes['private-game.g1a'] = hashlib.sha256(b'never redistribute').hexdigest()
        (self.artifacts / 'manifest.json').write_text(json.dumps({'schemaVersion': 2, 'bundleFormat': 2, 'files': hashes}))

    def packaged_job(self, package, *arguments):
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                                 str(package / 'tooling/profile_job.py'), *map(str, arguments)],
                                cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.splitlines()[-1])['result']

    def test_upgrade_rebuilds_loader_files_and_leaves_native_sdk_in_place(self):
        for old in ('loader-artifacts/ExtLoad.g1a', 'ProfileStudio/ProfileStudio.exe',
                    'ProfileStudio/engine/tooling/ext_profile.py', 'tooling/ext_profile.py',
                    'desktop/ProfileStudio/VALIDATION.json', 'probes/extended-loader/src/main.c',
                    'sdk/fxlarge/CMakeLists.txt', 'sdk/examples/oversized-loader/old.c'):
            with self.subTest(old=old):
                self.assertFalse(inherited_file(old))
        for keep in ('sdk/native/host/python/python.exe', 'examples/counter-c/CMakeLists.txt'):
            self.assertTrue(inherited_file(keep))

    def test_packaged_default_flash_path_is_complete_and_allowlisted(self):
        package = self.root / 'portable'
        packages.copy_loader_runtime(ROOT, self.artifacts, package)
        data = bytearray(0x260)
        data[:8] = bytes(x ^ 255 for x in b'USBPower')
        data[0x200:0x208] = bytes.fromhex('d103d004412b0009')
        struct.pack_into('>II', data, 0x210, 0x80010070, 0x90f)
        source = self.root / 'synthetic.g1a'
        source.write_bytes(data)
        job = self.packaged_job(package, 'generate', '--input', source, '--output-root', self.root / 'result')
        output = Path(job['output'])
        app = output / 'calculator/FXAPPS' / job['identity']['calculatorId']
        self.assertEqual(job['status'], 'program-ready')
        self.assertFalse(job['includesLoader'])
        self.assertEqual((app / 'IMAGE.BIN').read_bytes(), data)
        self.assertEqual((app / 'APP.FPF').read_bytes()[:8], b'FXLDF001')
        self.assertTrue((app / 'APP.MET').is_file())
        self.assertFalse((output / 'calculator/FlashLd.g1a').exists())
        attached = self.packaged_job(package, 'generate', '--input', source,
                                    '--output', self.root / 'attached', '--include-loader')
        self.assertEqual(attached['status'], 'candidate')
        self.assertEqual((Path(attached['output']) / 'calculator/FlashLd.g1a').read_bytes(),
                         (self.artifacts / 'FlashLd.g1a').read_bytes())
        self.assertFalse((package / 'loader-artifacts/private-game.g1a').exists())
        manifest = json.loads((package / 'loader-artifacts/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(set(manifest['files']), set(packages.LOADER_BINARIES))
        self.assertEqual((manifest['schemaVersion'], manifest['bundleFormat']), (2, 2))

    def test_package_with_legacy_artifacts_exports_only_standard_launchers(self):
        package = self.root / 'portable'
        (self.artifacts / 'KLoad.g1a').write_bytes(b'historical')
        extra = self.artifacts / 'ExtLoad.g1a'
        extra.write_bytes(b'legacy')
        manifest = self.artifacts / 'manifest.json'
        record = json.loads(manifest.read_text())
        record['files'][extra.name] = packages.digest(extra)
        manifest.write_text(json.dumps(record))
        packages.copy_loader_runtime(ROOT, self.artifacts, package)
        self.assertFalse((package / 'loader-artifacts' / extra.name).exists())
        self.assertFalse((package / 'loader-artifacts/KLoad.g1a').exists())
        self.assertFalse((package / 'tooling/ext_profile.py').exists())
        self.assertFalse((package / 'probes/mapped-loader/vendor/fxlarge').exists())
        self.assertTrue((package / 'probes/mapped-loader/include/fxlarge/catalog.h').is_file())
        exported = self.root / 'launchers'
        result = self.packaged_job(package, 'export-loader', '--output', exported)
        self.assertEqual(result['loaders'], ['FlashLd.g1a'])
        self.assertFalse((exported / 'private-game.g1a').exists())

    def test_old_artifact_format_and_modified_public_component_are_rejected(self):
        record = json.loads((self.artifacts / 'manifest.json').read_text(encoding='utf-8'))
        (self.artifacts / 'manifest.json').write_text(json.dumps({'files': record['files']}))
        with self.assertRaisesRegex(ValueError, 'bundleFormat 2'):
            packages.copy_loader_runtime(ROOT, self.artifacts, self.root / 'old')
        self.assertFalse((self.root / 'old').exists())
        (self.artifacts / 'manifest.json').write_text(json.dumps(record))
        source = self.root / 'source'
        for relative in set(packages.public_component_sources(ROOT)) | packages.SDK_EDITION_FILES:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        (source / 'probes/storage-loader/tools/prepare.py').write_text('# modified after component publication\n')
        with self.assertRaisesRegex(ValueError, 'public source lock'):
            packages.copy_loader_runtime(source, self.artifacts, self.root / 'changed-components')
        self.assertFalse((self.root / 'changed-components').exists())

    def test_missing_or_changed_launcher_rejected_before_output(self):
        (self.artifacts / 'FlashLd.g1a').unlink()
        with self.assertRaisesRegex(ValueError, 'FlashLd.g1a'):
            packages.copy_loader_runtime(ROOT, self.artifacts, self.root / 'missing')
        self.assertFalse((self.root / 'missing').exists())
        (self.artifacts / 'FlashLd.g1a').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            packages.copy_loader_runtime(ROOT, self.artifacts, self.root / 'changed')
        self.assertFalse((self.root / 'changed').exists())

    def test_component_source_inventory_contains_linker_assembly_and_flash_tools(self):
        paths = packages.public_component_sources(ROOT)
        for name in ('loader-components.lock.json',
                     'probes/storage-loader/src/start.S',
                     'probes/storage-loader/src/probe.ld',
                     'probes/storage-loader/tools/prepare.py',
                     'probes/os-map-profile.h', packages.EXAMPLE + '/probes/extended-cas/payload-api.h',
                     'sdk/caller-session/include/fx_caller_session.h',
                     packages.EXAMPLE + '/probes/source-guest/vendor/fxlarge/include/fxlarge/runtime.h'):
            self.assertIn(name, paths)
        self.assertFalse(any(Path(p).suffix.lower() in ('.bin', '.rom', '.g1a') for p in paths))

    def test_development_resources_survive_relocation_without_build_outputs(self):
        source = self.root / 'dev-source'
        for name in (*packages.DEVELOPMENT_FILES,
                     'compat/fxlib/include/fxlib.h', 'compat/fxlib/src/fxlib.c',
                     'examples/legacy-fxlib/CMakeLists.txt',
                     'examples/legacy-fxlib/src/main.c'):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('portable fixture')
        ignored = source / 'examples/legacy-fxlib/build-Release/private.g1a'
        ignored.parent.mkdir(parents=True)
        ignored.write_bytes(b'private build')
        output = self.root / 'dev-package'
        packages.copy_development_runtime(source, output)
        self.assertEqual((output / 'compat/fxlib/include/fxlib.h').read_text(encoding='utf-8'), 'portable fixture')
        self.assertTrue((output / 'tooling/legacy_project.py').is_file())
        self.assertFalse((output / 'examples/legacy-fxlib/build-Release').exists())


class EmulatorFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.build / 'FxEmulator.exe').write_bytes(b'authored binary fixture')
        self.record = {'upstreamCommit': freshness.UPSTREAM, 'executable': 'FxEmulator.exe',
                       'bytes': (self.build / 'FxEmulator.exe').stat().st_size,
                       'sha256': packages.digest(self.build / 'FxEmulator.exe'), 'bridgeSources': []}
        for name in freshness.BRIDGE_SOURCES:
            path = self.root / 'probes/emulator' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('authored source ' + name)
            self.record['bridgeSources'].append({'name': name, 'sha256': packages.digest(path)})
        for name, field in [('debugger-hooks.patch', 'sourcePatchSha256'),
                            ('runtime-compat.patch', 'compatibilityPatchSha256')]:
            path = self.root / 'probes/emulator' / name
            path.write_text('authored patch')
            self.record[field] = packages.digest(path)
        self.save()

    def save(self):
        (self.build / 'BUILD-MANIFEST.json').write_text(json.dumps(self.record))

    def test_current_manifest_and_binary_pass(self):
        self.assertTrue(freshness.verify_emulator_build(self.root, self.build)['passed'])

    def test_stale_source_rejected_even_when_binary_matches_manifest(self):
        (self.root / 'probes/emulator/hardware_model.c').write_text('new source')
        with self.assertRaisesRegex(ValueError, 'source changed after build'):
            freshness.verify_emulator_build(self.root, self.build)

    def test_binary_patch_and_incomplete_inventory_fail(self):
        (self.build / 'FxEmulator.exe').write_bytes(b'changed')
        self.record['bridgeSources'].pop()
        self.record['sourcePatchSha256'] = '0' * 64
        self.save()
        with self.assertRaises(ValueError) as caught:
            freshness.verify_emulator_build(self.root, self.build)
        for message in ('executable', 'inventory', 'patch changed'):
            self.assertIn(message if message != 'executable' else 'FxEmulator.exe', str(caught.exception))

    def test_isolated_build_generated_patches_and_upstream_inputs_are_bound(self):
        self.record['generatedPatches'] = {}
        for name in ('debugger-hooks.patch', 'runtime-compat.patch'):
            data = (self.root / 'probes/emulator' / name).read_bytes()
            (self.build / name).write_bytes(data)
            self.record['generatedPatches'][name] = packages.digest(self.build / name)
        upstream = self.root / 'third_party/emuCasioCalc/src/engine/cpu.c'
        upstream.parent.mkdir(parents=True)
        upstream.write_text('pinned input')
        self.record['upstreamSources'] = {upstream.relative_to(self.root).as_posix(): packages.digest(upstream)}
        self.save()
        output = self.root / 'packaged-emulator'
        freshness.copy_verified_emulator(self.root, self.build, output)
        self.assertTrue(freshness.verify_emulator_build(self.root, output)['passed'])
        upstream.write_text('changed upstream')
        with self.assertRaisesRegex(ValueError, 'upstream source changed'):
            freshness.verify_emulator_build(self.root, output)


if __name__ == '__main__':
    unittest.main()
