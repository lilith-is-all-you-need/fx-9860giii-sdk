from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT/'dist-toolchain/native-sdk'
for name in ('build-native.py', 'build-project.py', 'compiler-launcher.py'):
    shutil.copy2(ROOT/'tooling'/name, DEST/'service'/name)
records = []
for file in sorted(DEST.rglob('*')):
    if file.is_file() and file != DEST/'manifest.json':
        records.append({'path': file.relative_to(DEST).as_posix(), 'bytes': file.stat().st_size,
                        'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
manifest = {'schemaVersion': 1, 'compiler': 'GCC 14.1.0', 'target': 'sh3eb-elf',
            'binutils': '2.42', 'files': records, 'totalBytes': sum(f['bytes'] for f in records)}
(DEST/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(f'Finalized {len(records)} files, {manifest["totalBytes"]:,} bytes')
