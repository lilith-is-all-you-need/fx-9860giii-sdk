"""Portable CLI contracts; temporary workspaces, no target build or network."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/fxstudio/scripts/engineering.py'
spec = importlib.util.spec_from_file_location('engineering', SCRIPT)
engineering = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engineering)


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fx 工程 ' ")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, code=0):
        proc = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, encoding='utf8', timeout=15)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_scaffold_is_portable_and_never_overwrites(self):
        project = self.root / 'guarded'
        self.cli('new', 'guarded-c', project)
        self.assertTrue((project / 'src/model.c').is_file())
        (project / 'owned.txt').write_text('preserve')
        self.cli('new', 'guarded-c', project, code=1)
        self.assertEqual((project / 'owned.txt').read_text(), 'preserve')

    def test_snapshot_tracks_content_additions_deletions_and_ignores_host_state(self):
        project = self.root / 'project'
        self.cli('new', 'guarded-c', project)
        ignored = project / '.fxstudio'
        ignored.mkdir()
        (ignored / 'bridge.json').write_text('{"credential":"do-not-copy"}')
        (project / 'build-debug').mkdir()
        (project / 'build-debug' / 'generated.c').write_text('ignored')
        baseline = ignored / 'baseline.json'
        self.cli('snapshot', project, '--output', baseline)
        before = baseline.read_bytes()
        self.cli('compare', project, '--snapshot', baseline)
        source = project / 'src/model.c'
        original = source.read_bytes()
        source.write_bytes(original.replace(b'FX_OK', b'FX_OX'))  # same-length content change
        (project / 'src/new.c').write_text('new')
        (project / 'src/contract.c').unlink()
        result = self.cli('compare', project, '--snapshot', baseline, code=2)
        self.assertEqual(result['changed'], ['src/model.c'])
        self.assertEqual(result['added'], ['src/new.c'])
        self.assertEqual(result['removed'], ['src/contract.c'])
        self.assertEqual(baseline.read_bytes(), before)
        self.cli('snapshot', project, '--output', baseline, code=1)

    def test_empty_and_untrusted_snapshot_rejected(self):
        project = self.root / 'empty'
        project.mkdir()
        self.cli('snapshot', project, '--output', self.root / 'empty.json', code=1)
        (project / 'x.c').write_text('x')
        bad = self.root / 'bad.json'
        bad.write_text(json.dumps({'schemaVersion': 1, 'kind': 'source-snapshot',
                                  'scope': 'source-text-and-assets-v1',
                                  'files': [{'path': '../outside.c'}]}))
        self.cli('compare', project, '--snapshot', bad, code=1)

    def test_budget_honors_reserve_and_does_not_claim_hardware(self):
        artifact = self.root / 'test.g1a'
        artifact.write_bytes(b'x' * 1000)  # deliberately invalid G1A, only byte budget tested
        policy = self.root / 'policy.json'
        policy.write_text(json.dumps({'schemaVersion': 1, 'kind': 'project-policy',
                                      'maxG1aBytes': 1100, 'reserveBytes': 100,
                                      'basis': 'unit-test policy'}))
        result = self.cli('budget', artifact, '--policy', policy)
        self.assertEqual(result['remainingBytes'], 0)
        self.assertEqual(result['hardware'], 'not_tested')
        self.assertEqual(result['pairingAndStructure'], 'not_checked_use_sdk_build_verifier')
        artifact.write_bytes(b'x' * 1001)
        report = self.root / 'budget.json'
        self.cli('budget', artifact, '--policy', policy, '--output', report, code=2)
        self.assertFalse(json.loads(report.read_text())['ok'])
        self.cli('budget', artifact, '--policy', policy, '--output', report, code=1)

    def test_policy_needs_source_and_valid_integer_units(self):
        artifact = self.root / 'test.g1a'
        artifact.write_bytes(b'x' * 700)
        policy = self.root / 'policy.json'
        for value in ({'schemaVersion': 1, 'kind': 'hardware-limit', 'maxG1aBytes': 900, 'basis': 'guess'},
                      {'schemaVersion': 1, 'kind': 'project-policy', 'maxG1aBytes': True, 'basis': 'guess'},
                      {'schemaVersion': 1, 'kind': 'project-policy', 'maxG1aBytes': 900, 'basis': ''}):
            policy.write_text(json.dumps(value))
            self.cli('budget', artifact, '--policy', policy, code=1)

    def test_hardware_record_binds_file_without_fabricating_success(self):
        artifact = self.root / 'candidate.g1a'
        artifact.write_bytes(b'x' * 900)
        output = self.root / 'device.json'
        self.cli('hardware-record', artifact, '--output', output)
        data = json.loads(output.read_text())
        self.assertEqual(data['artifact']['sha256'], engineering.sha(artifact))
        self.assertTrue(all(item['status'] == 'not_run' for item in data['checks'].values()))
        self.assertIsNone(data['device']['osVersion'])
        self.cli('hardware-record', artifact, '--output', output, code=1)


if __name__ == '__main__':
    unittest.main()
