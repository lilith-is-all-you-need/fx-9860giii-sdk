"""Refresh the matching source companion and checksums in our assembled release."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / 'dist-windows/FxStudio-0.1.1-win-x64'
manifest_path = target / 'package-manifest.json'
old = json.loads(manifest_path.read_text(encoding='utf8'))
assert old['name'] == target.name and target.resolve().parent == (ROOT/'dist-windows').resolve()

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

source = ROOT / 'dist-windows/FxStudio-0.1.1-sources.zip'
source_manifest = source.with_suffix('.manifest.json')
assert digest(source) == json.loads(source_manifest.read_text(encoding='utf8'))['sha256']
for path in (source, source_manifest):
    shutil.copy2(path, target/'sources'/path.name)
files = [{'path': p.relative_to(target).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)}
         for p in sorted(target.rglob('*')) if p.is_file() and p != manifest_path]
manifest_path.write_text(json.dumps({'schemaVersion':1, 'name':target.name, 'files':files}, indent=2)+'\n', encoding='utf8')
archive = target.parent / (target.name+'.zip')
temporary = archive.with_suffix('.zip.partial')
with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
    for path in sorted(target.rglob('*')):
        if path.is_file():
            zipped.write(path, target.name+'/'+path.relative_to(target).as_posix(),
                         compress_type=zipfile.ZIP_STORED if path.suffix.lower()=='.zip' else zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(temporary) as zipped:
    assert zipped.testzip() is None, 'Package ZIP has a corrupt member'
temporary.replace(archive)
checksum = digest(archive)
archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n', encoding='ascii')
(ROOT/'sdk/package-validation.json').write_text(json.dumps({'passed':True, 'archive':archive.name,
    'bytes':archive.stat().st_size, 'sha256':checksum, 'files':len(files), 'zipCrcPassed':True}, indent=2), encoding='utf8')
print(json.dumps({'archive':str(archive), 'bytes':archive.stat().st_size, 'sha256':checksum, 'files':len(files)}, indent=2))
