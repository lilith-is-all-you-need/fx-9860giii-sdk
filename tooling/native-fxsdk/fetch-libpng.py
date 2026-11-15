"""Archive the exact installed MSYS2 libpng recipe, APNG patch and upstream source."""
from pathlib import Path
import hashlib,json,urllib.request,subprocess,shutil
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'dist-toolchain/native-fxsdk/dependency-sources/mingw-w64-libpng'
OUT.mkdir(parents=True,exist_ok=True)
manifest=OUT/'manifest.json'
if manifest.exists():
    meta=json.loads(manifest.read_text(encoding='utf-8'))
else:
    meta={'package':'mingw-w64-x86_64-libpng','version':'1.6.59-2','files':[
       {'name':'mingw-w64-libpng-1.6.59-2.src.tar.zst','url':'https://repo.msys2.org/mingw/sources/mingw-w64-libpng-1.6.59-2.src.tar.zst'}]}
for entry in meta['files']:
    file=OUT/entry['name']
    if not file.exists():
        with urllib.request.urlopen(entry['url'],timeout=120) as stream: file.write_bytes(stream.read())
    sha=hashlib.sha256(file.read_bytes()).hexdigest()
    if entry.get('sha256') and entry['sha256']!=sha: raise RuntimeError('Checksum mismatch: '+entry['name'])
    entry.update(sha256=sha,bytes=file.stat().st_size)
subprocess.run(['tar.exe','-xf',str(OUT/meta['files'][0]['name']),'-C',str(OUT)],check=True)
recipe=next(OUT.rglob('PKGBUILD')).read_text(encoding='utf-8')
if 'pkgver=1.6.59\n' not in recipe or 'pkgrel=2\n' not in recipe: raise RuntimeError('Recipe version does not match the installed binary')
installed=Path('C:/msys64/var/lib/pacman/local/mingw-w64-x86_64-libpng-1.6.59-2/desc')
(OUT/'installed-package.desc').write_bytes(installed.read_bytes())
meta['staticLibrarySha256']=hashlib.sha256(Path('C:/msys64/mingw64/lib/libpng.a').read_bytes()).hexdigest()
zlib_meta=json.loads((ROOT/'dist-toolchain/native-gdb/dependency-manifest.json').read_text(encoding='utf-8'))
zlib_entry=next(item for item in zlib_meta['sources'] if item['file']=='mingw-w64-zlib-1.3.1-1.src.tar.zst')
zlib_source=ROOT/'dist-toolchain/native-gdb/dependency-sources'/zlib_entry['file']
if hashlib.sha256(zlib_source.read_bytes()).hexdigest()!=zlib_entry['sha256']: raise RuntimeError('Cached zlib checksum mismatch')
shutil.copy2(zlib_source,OUT.parent/zlib_entry['file'])
meta['zlib']=zlib_entry
manifest.write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
print(json.dumps(meta,indent=2))
