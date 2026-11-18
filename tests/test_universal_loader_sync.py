"""Regression coverage for upgrading the two original Loader pins to one commit."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tooling'))
from sync_loader_components import EXAMPLE, SPLIT, UNIFIED, sync


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding='utf-8')


class UnifiedLoaderSync(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name).resolve()
        self.sdk = self.base / 'sdk'
        self.sdk.mkdir()
        self.repo = self.base / 'upstream'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.make_manifest(self.repo, {'sdk/caller-session/api.h': b'caller',
                                       'probes/os-map-shared.h': b'shared'})
        self.make_manifest(self.repo / 'large', {'probes/source-guest/main.c': b'large',
                                                 'probes/os-map-shared.h': b'shared'})
        self.commit()
        self.lock = self.sdk / 'loader-components.lock.json'
        components = [{'name': name, 'repository': 'historical', 'commit': 'b' * 40, 'files': {}}
                      for name in ('fx9860-emulator', *SPLIT)]
        write_json(self.lock, {'schemaVersion': 1, 'components': components})

    def make_manifest(self, directory, members):
        for rel, data in members.items():
            target = directory / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        write_json(directory / 'source-manifest.json', {'files': {rel: sha(data) for rel, data in members.items()}})

    def commit(self):
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=fixture',
                        '-c', 'user.email=fixture@localhost', 'commit', '-qm', 'snapshot'], check=True)
        return subprocess.check_output(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], text=True).strip()

    def test_migration_and_update_keep_existing_include_and_probe_paths(self):
        sync({UNIFIED: self.repo}, root=self.sdk)
        first = self.lock.read_bytes()
        lock = json.loads(first)
        self.assertEqual([c['name'] for c in lock['components']], ['fx9860-emulator', UNIFIED])
        loader = lock['components'][1]
        self.assertEqual(loader['sourcePaths'][(EXAMPLE + '/probes/source-guest/main.c')], 'large/probes/source-guest/main.c')
        self.assertEqual(loader['sourcePaths']['probes/os-map-shared.h'], 'probes/os-map-shared.h')
        self.assertFalse((self.sdk/'sdk/fxlarge').exists())
        self.assertEqual((self.sdk/'sdk/caller-session/api.h').read_bytes(), b'caller')
        sync({UNIFIED: self.repo}, root=self.sdk)
        self.assertEqual(self.lock.read_bytes(), first)
        self.make_manifest(self.repo/'large', {'probes/source-guest/main.c': b'updated'})
        revision = self.commit()
        sync({UNIFIED: self.repo}, root=self.sdk)
        self.assertEqual(json.loads(self.lock.read_bytes())['components'][1]['commit'], revision)
        self.assertEqual((self.sdk/(EXAMPLE + '/probes/source-guest/main.c')).read_bytes(), b'updated')
        self.assertEqual((self.sdk/'probes/os-map-shared.h').read_bytes(), b'shared')
        self.assertFalse((self.sdk/EXAMPLE/'probes/os-map-shared.h').exists())

    def test_conflicting_shared_header_leaves_sdk_untouched(self):
        self.make_manifest(self.repo/'large', {'probes/os-map-shared.h': b'incompatible'})
        self.commit()
        before = self.lock.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Conflicting shared source'):
            sync({UNIFIED: self.repo}, root=self.sdk)
        self.assertEqual(self.lock.read_bytes(), before)
        self.assertEqual(list(self.sdk.iterdir()), [self.lock])


if __name__ == '__main__':
    unittest.main()
