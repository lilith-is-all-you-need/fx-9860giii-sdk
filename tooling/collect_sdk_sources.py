"""Collect public SDK source snapshots and GPL toolchain sources on Windows."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist-toolchain/sources/sdk'
KHICAS=ROOT.parent/'print_cd_data_side/khicas-dev'
REPOS={
    'fxSDK':KHICAS/'fxSDK',
    'gint':Path('C:/khicas-work/forge-cache/gint'),
    'fxlibc':Path('C:/khicas-work/forge-cache/fxlibc'),
    'OpenLibm':Path('C:/khicas-work/forge-cache/OpenLibm'),
    'sh-elf-gcc-build':KHICAS/'sh-elf-gcc',
    'sh-elf-binutils-build':Path('C:/khicas-work/sh-elf-binutils-cache'),
}
URLS=[
    'https://ftp.gnu.org/gnu/gcc/gcc-14.1.0/gcc-14.1.0.tar.xz',
    'https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz',
]

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def download(url):
    p=OUT/url.rsplit('/',1)[1]
    if not p.exists():
        with urllib.request.urlopen(url,timeout=120) as source,p.with_suffix(p.suffix+'.part').open('wb') as dest:
            while chunk:=source.read(1024*1024):dest.write(chunk)
        p.with_suffix(p.suffix+'.part').replace(p)
    print('Source:',p.name,flush=True)
    return {'file':p.name,'url':url,'bytes':p.stat().st_size,'sha256':digest(p)}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records=[]
    for name,repo in REPOS.items():
        revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        url=subprocess.check_output(['git','-C',str(repo),'remote','get-url','origin'],text=True).strip()
        archive=OUT/(name+'-'+revision[:12]+'.tar.gz')
        subprocess.run(['git','-C',str(repo),'archive','--format=tar.gz','--prefix='+name+'/',
                        '--output='+str(archive),'HEAD'],check=True)
        patch=subprocess.check_output(['git','-C',str(repo),'diff','--binary','HEAD'])
        if patch:(OUT/(name+'-local-changes.patch')).write_bytes(patch)
        records.append({'component':name,'revision':revision,'url':url,'file':archive.name,
                        'bytes':archive.stat().st_size,'sha256':digest(archive),
                        'localPatch':name+'-local-changes.patch' if patch else None})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        records.extend(pool.map(download,URLS))
    with tarfile.open(OUT/'gcc-14.1.0.tar.xz') as tar:
        text=tar.extractfile('gcc-14.1.0/contrib/download_prerequisites').read().decode()
    # GCC ships exact archive versions in this script. Include the source for
    # mathematical libraries statically linked into cc1, not only GCC itself.
    prerequisites=[]
    for line in text.splitlines():
        if any(line.startswith(name+'=') for name in ('gmp','mpfr','mpc','isl')):
            name=line.split('=',1)[1].strip('"\'')
            prerequisites.append('https://gcc.gnu.org/pub/gcc/infrastructure/'+name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records.extend(pool.map(download,prerequisites))
    (OUT/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
