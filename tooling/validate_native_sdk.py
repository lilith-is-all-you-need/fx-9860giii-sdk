"""Build this release's own C/C++ examples using bundled dependencies only."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(sys.argv[1]).resolve()
OUT = ROOT / 'sdk/native-validation'
OUT.mkdir(parents=True, exist_ok=True)
python = SDK / 'host/python/python.exe'
script = SDK / 'service/build-native.py'
env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot']) / 'System32'),
           PYTHONUTF8='1', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9')
results = []

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for name in ('counter-c', 'counter-cpp'):
    source = ROOT / 'examples' / name
    originals = {str(p): digest(p) for p in source.rglob('*') if p.is_file() and '.fxstudio' not in p.relative_to(source).parts}
    for configuration in ('Debug', 'Release'):
        output = source / '.fxstudio/build' / configuration
        before = time.monotonic()
        log = OUT / (name + '-' + configuration + '.log')
        with log.open('w', encoding='utf8') as stream:
            process = subprocess.run([str(python), str(script), str(SDK), str(source), str(output), configuration],
                                     env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        result = {'example': name, 'configuration': configuration, 'exitCode': process.returncode,
                  'seconds': round(time.monotonic() - before, 2), 'log': log.name}
        if process.returncode == 0:
            manifest = json.loads((output / 'artifact.json').read_text(encoding='utf8'))
            result.update(g1aBytes=manifest['g1aBytes'], sha256=manifest['sha256'], artifactPair=manifest['artifactPair'])
        else:
            print(log.read_text(encoding='utf8')[-7000:])
        result['sourceUnchanged'] = all(Path(p).is_file() and digest(Path(p)) == value for p, value in originals.items())
        result['passed'] = process.returncode == 0 and result['sourceUnchanged']
        results.append(result)
        print(name, configuration, 'PASS' if result['passed'] else 'FAIL', flush=True)

record = {'schemaVersion': 1, 'passed': all(r['passed'] for r in results),
          'sdkDirectory': str(SDK), 'checks': results, 'systemPathOnly': True,
          'networkDependenciesUsed': False, 'httpProxyRejectsConnections': True,
          'networkInterfaceDisabled': False, 'hardwareTested': False}
(ROOT / 'sdk/native-validation.json').write_text(json.dumps(record, indent=2), encoding='utf8')
raise SystemExit(0 if record['passed'] else 1)
