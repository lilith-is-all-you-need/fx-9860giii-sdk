"""Fetch pinned portable Windows dependencies; retain archives and SHA-256 evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,urllib.request,zipfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'dist-toolchain/native-fxsdk'
CACHE=OUT/'archives'
PREFIX=OUT/'prefix'
CACHE.mkdir(parents=True,exist_ok=True)

def download(item):
    name,url,dest,strip,expected=item
    file=CACHE/name
    if not file.exists():
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url,timeout=120) as response: file.write_bytes(response.read())
                break
            except (OSError,TimeoutError):
                if attempt==3: raise
                time.sleep(1)
    sha=hashlib.sha256(file.read_bytes()).hexdigest()
    if expected and sha!=expected: raise RuntimeError('Download checksum mismatch: '+name)
    target=PREFIX/dest
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(file) as archive:
        for member in archive.infolist():
            path=Path(*Path(member.filename).parts[strip:])
            if not path.parts: continue
            output=target/path
            if not output.resolve().is_relative_to(target.resolve()): raise RuntimeError('Unsafe archive path')
            if member.is_dir(): output.mkdir(parents=True,exist_ok=True)
            else:
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_bytes(archive.read(member))
    return {'name':name,'url':url,'sha256':sha,'bytes':file.stat().st_size,'destination':dest}

items=[
 ('python-3.13.7-embeddable-amd64.zip','https://www.python.org/ftp/python/3.13.7/python-3.13.7-embeddable-amd64.zip','host/python',0,'e201b2da753a88c1af29d87f9f48af4d64a0fc8522a204ae672bd2c382496701'),
 ('cmake-3.31.8-windows-x86_64.zip','https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8-windows-x86_64.zip','host/cmake',1,'81aa9964dbabd71fe02e7ec50472fd3ad56138c49944515ece9001efbff8d719'),
 ('ninja-win-1.13.1.zip','https://github.com/ninja-build/ninja/releases/download/v1.13.1/ninja-win.zip','host/ninja',0,'26a40fa8595694dec2fad4911e62d29e10525d2133c9a4230b66397774ae25bf'),
 ('pillow-11.3.0-cp313-cp313-win_amd64.whl','https://files.pythonhosted.org/packages/23/85/397c73524e0cd212067e0c969aa245b01d50183439550d24d9f55781b776/pillow-11.3.0-cp313-cp313-win_amd64.whl','host/python/Lib/site-packages',0,'0bce5c4fd0921f99d2e858dc4d4d64193407e1b99478bc5cacecba2311abde51')]
with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(download,items))
(PREFIX/'host/python/python313._pth').write_text('python313.zip\n.\nLib/site-packages\n../../bin\n',encoding='ascii')
(OUT/'host-dependencies.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,indent=2))
