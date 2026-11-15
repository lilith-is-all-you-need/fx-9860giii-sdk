"""Cache the source releases matching the bundled portable host binaries."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib,json,time,urllib.request,tarfile
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'dist-toolchain/native-fxsdk'
CACHE=OUT/'archives'
CACHE.mkdir(parents=True,exist_ok=True)
manifest_path=OUT/'source-archives.json'
if manifest_path.exists():
    entries=json.loads(manifest_path.read_text(encoding='utf-8'))
else:
    pillow=json.load(urllib.request.urlopen('https://pypi.org/pypi/pillow/11.3.0/json'))
    source=next(item for item in pillow['urls'] if item['packagetype']=='sdist')
    entries=[
      {'name':'Python-3.13.7.tgz','url':'https://www.python.org/ftp/python/3.13.7/Python-3.13.7.tgz'},
      {'name':'cmake-3.31.8.tar.gz','url':'https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8.tar.gz'},
      {'name':'ninja-1.13.1.tar.gz','url':'https://codeload.github.com/ninja-build/ninja/tar.gz/refs/tags/v1.13.1'},
      {'name':source['filename'],'url':source['url'],'sha256':source['digests']['sha256']}]
def fetch(entry):
    dest=CACHE/entry['name']
    if not dest.exists():
        for attempt in range(4):
            try:
                with urllib.request.urlopen(entry['url'],timeout=120) as stream: dest.write_bytes(stream.read())
                break
            except (OSError,TimeoutError):
                if attempt==3: raise
                time.sleep(1)
    sha=hashlib.sha256(dest.read_bytes()).hexdigest()
    if entry.get('sha256') and entry['sha256']!=sha: raise RuntimeError('Source checksum mismatch: '+entry['name'])
    return dict(entry,sha256=sha,bytes=dest.stat().st_size)
with ThreadPoolExecutor(max_workers=4) as pool: result=list(pool.map(fetch,entries))
manifest_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
with tarfile.open(CACHE/'ninja-1.13.1.tar.gz') as archive:
    member=next(item for item in archive.getmembers() if item.name.endswith('/COPYING'))
    license_file=OUT/'prefix/licenses/ninja-LICENSE.txt'
    license_file.parent.mkdir(parents=True,exist_ok=True)
    license_file.write_bytes(archive.extractfile(member).read())
print(json.dumps(result,indent=2))
