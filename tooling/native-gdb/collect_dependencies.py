"""Preserve exact MSYS2 source packages for statically linked GDB dependencies."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'dist-toolchain/native-gdb'
SOURCES=OUT/'dependency-sources'
PACKAGES=('gcc','gcc-libs','gmp','mpfr','zlib','libiconv','expat','winpthreads','crt-git','headers-git','termcap')

def desc(path):
    return {key:value.strip() for key,value in re.findall(r'%([^%]+)%\n([^%]*)',path.read_text())}

def download(item):
    name,url=item
    p=SOURCES/name
    if not p.exists():
        with urllib.request.urlopen(url,timeout=120) as src,p.with_suffix(p.suffix+'.part').open('wb') as dst:
            while chunk:=src.read(1024*1024):dst.write(chunk)
        p.with_suffix(p.suffix+'.part').replace(p)
    with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    print('Dependency source:',name,flush=True)
    return {'file':name,'url':url,'bytes':p.stat().st_size,'sha256':sha}

def main():
    SOURCES.mkdir(parents=True,exist_ok=True)
    packages=[];files={}
    for name in PACKAGES:
        matches=list(Path('C:/msys64/var/lib/pacman/local').glob('mingw-w64-x86_64-'+name+'-*/desc'))
        matches=[p for p in matches if desc(p)['NAME']=='mingw-w64-x86_64-'+name]
        if len(matches)!=1:raise RuntimeError('Ambiguous installed dependency: '+name)
        fields=desc(matches[0])
        packages.append({k.lower():fields[k] for k in ('NAME','VERSION','BASE','LICENSE')})
        filename=fields['BASE']+'-'+fields['VERSION']+'.src.tar.zst'
        files[filename]='https://repo.msys2.org/mingw/sources/'+filename
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        downloads=list(pool.map(download,files.items()))
    (OUT/'dependency-manifest.json').write_text(json.dumps({'packages':packages,'sources':downloads},indent=2)+'\n')
    licenses=OUT/'licenses';licenses.mkdir(exist_ok=True)
    for name in ('crt','gcc-libs','winpthreads','libiconv','zlib','expat'):
        source=Path('C:/msys64/mingw64/share/licenses')/name
        if source.exists():shutil.copytree(source,licenses/name,dirs_exist_ok=True)

if __name__=='__main__':main()
