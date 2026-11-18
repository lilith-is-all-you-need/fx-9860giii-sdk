"""Run the documented source fixture independently of the product profile engine."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

EXAMPLE = Path(__file__).resolve().parents[1] / 'sdk/examples/oversized-loader'


class SourceExample(unittest.TestCase):
    def test_513_page_fixture(self):
        spec = importlib.util.spec_from_file_location('example_profile', EXAMPLE / 'tooling/ext_profile.py')
        codec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(codec)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            guest = directory / 'guest.g1a'
            guest.write_bytes(bytes(512) + bytes.fromhex('00090009'))
            target = directory / 'FXAPPS/DEMO513'
            subprocess.run([sys.executable, str(EXAMPLE / 'tests/make_source_guest.py'),
                            str(guest), str(target), '--bytes', '2097156'], check=True)
            image = (target / 'IMAGE.BIN').read_bytes()
            profile = codec.decode_profile((target / 'EXT.PRF').read_bytes())
            self.assertEqual(profile['sha256'], hashlib.sha256(image).hexdigest())
            self.assertEqual((profile['imageBytes'], profile['pageCount'], profile['pageCapacity']),
                             (2097156, 513, 528))
            self.assertEqual(struct.unpack_from('>I', image, 2097152)[0], 0xfaca0200)


if __name__ == '__main__':
    unittest.main()
