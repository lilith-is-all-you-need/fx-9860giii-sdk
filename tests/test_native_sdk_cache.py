"""SDK deployment regression: no short names, interrupted cache, edits and repair."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native', ROOT / 'tooling/build-native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class SdkCacheTests(unittest.TestCase):
    def test_snapshot_integrity_and_recovery_without_short_names(self):
        with tempfile.TemporaryDirectory(prefix='FxStudio-sdk-test-') as temporary:
            root = Path(temporary)
            sdk = root / "中文's SDK"
            (sdk / 'bin').mkdir(parents=True)
            original = sdk / 'bin/compiler.exe'
            original.write_bytes(b'compiler-v1')
            (sdk / 'service').mkdir()
            (sdk / 'service/build.py').write_bytes(b'build-v1')
            cache = root / 'cache'; cache.mkdir()
            # A volume with no 8.3 aliases must work even on test hosts with them.
            with patch.object(native, 'ascii_path', side_effect=RuntimeError('no short names')):
                first = native.prepare_sdk(sdk, cache)
                self.assertTrue(str(first).isascii())
                self.assertEqual((first / 'bin/compiler.exe').read_bytes(), b'compiler-v1')
                mtime = (first / 'bin/compiler.exe').stat().st_mtime_ns
                again = native.prepare_sdk(sdk, cache)
                self.assertEqual(again, first)
                self.assertEqual((first / 'bin/compiler.exe').stat().st_mtime_ns, mtime)
                # Cache corruption and an interrupted copy must never be reused.
                (first / 'bin/compiler.exe').write_bytes(b'corrupt-v01')
                (first / 'service/build.py').unlink()
                native.prepare_sdk(sdk, cache)
                self.assertEqual((first / 'bin/compiler.exe').read_bytes(), b'compiler-v1')
                self.assertEqual((first / 'service/build.py').read_bytes(), b'build-v1')
                previous = original.stat()
                original.write_bytes(b'compiler-v2')
                os.utime(original, ns=(previous.st_atime_ns, previous.st_mtime_ns))
                second = native.prepare_sdk(sdk, cache)
                self.assertNotEqual(first, second)
                self.assertEqual((second / 'bin/compiler.exe').read_bytes(), b'compiler-v2')
                self.assertEqual((first / 'bin/compiler.exe').read_bytes(), b'compiler-v1')
                # Fail halfway through a new snapshot, then retry the same input.
                (sdk / 'service/build.py').write_bytes(b'build-v2')
                copy = native.shutil.copyfile
                def interrupt(source, target):
                    if Path(source).name == 'build.py':
                        raise OSError('simulated interruption')
                    return copy(source, target)
                with patch.object(native.shutil, 'copyfile', side_effect=interrupt):
                    with self.assertRaisesRegex(OSError, 'simulated interruption'):
                        native.prepare_sdk(sdk, cache)
                third = native.prepare_sdk(sdk, cache)
                self.assertEqual((third / 'service/build.py').read_bytes(), b'build-v2')
                self.assertEqual(original.read_bytes(), b'compiler-v2')

    def test_ascii_sdk_stays_in_place(self):
        sdk = Path('C:/FxStudio/sdk')
        with patch.object(native, 'ascii_path', return_value=sdk):
            self.assertEqual(native.prepare_sdk(sdk, Path('C:/unused-cache')), sdk)


if __name__ == '__main__':
    unittest.main()
