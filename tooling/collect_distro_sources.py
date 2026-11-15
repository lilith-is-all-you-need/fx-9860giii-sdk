"""Collect corresponding Ubuntu source archives for every installed package.

APT Sources indexes are fetched from official HTTPS repositories. Source files
are verified against their published SHA-256 and recorded in the offline pack.
Run only after provisioning has finished. Does not change the distribution.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import lzma
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist-toolchain/sources/ubuntu'
META=ROOT/'sdk/source-indexes'
DISTRO='FxSDK-Dev-20261114'

def records(text):
    for block in text.split('\n\n'):
        data={}
        key=None
        for line in block.splitlines():
            if line.startswith((' ','\t')) and key:
                data[key]+='\n'+line.strip()
            elif ': ' in line:
                key,value=line.split(': ',1)
                data[key]=value
            elif line.endswith(':'):
                key=line[:-1];data[key]=''
        if data:yield data

def fetch_index(item):
    suite,component=item
    host='security.ubuntu.com' if suite.endswith('security') else 'archive.ubuntu.com'
    url=f'https://{host}/ubuntu/dists/{suite}/{component}/source/Sources.xz'
    path=META/f'{suite}-{component}-Sources.xz'
    if not path.exists():
        with urllib.request.urlopen(url,timeout=120) as source,path.open('wb') as dest:
            while chunk:=source.read(1024*1024):dest.write(chunk)
    text=lzma.decompress(path.read_bytes()).decode()
    return list(records(text))

def fetch_file(entry):
    relative,checksum,size=entry
    path=OUT/relative.rsplit('/',1)[1]
    url='https://archive.ubuntu.com/ubuntu/'+relative
    def valid():
        if not path.is_file() or path.stat().st_size!=int(size):return False
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()==checksum
    if not valid():
        for retry in range(3):
            try:
                with urllib.request.urlopen(url,timeout=120) as source,path.with_suffix(path.suffix+'.part').open('wb') as dest:
                    while chunk:=source.read(1024*1024):dest.write(chunk)
                path.with_suffix(path.suffix+'.part').replace(path)
                if not valid():raise ValueError('Source checksum mismatch: '+path.name)
                break
            except Exception:
                if retry==2:raise
    return {'file':path.name,'sha256':checksum,'bytes':int(size),'url':url}

def main():
    OUT.mkdir(parents=True,exist_ok=True);META.mkdir(parents=True,exist_ok=True)
    queries=[(s,c) for s in ('noble','noble-updates','noble-security') for c in ('main','universe')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        indexes=[r for group in pool.map(fetch_index,queries) for r in group]
    if '--indexes-only' in sys.argv:return
    provisional='--provisional-status' in sys.argv
    if provisional:
        raw=Path(sys.argv[sys.argv.index('--provisional-status')+1]).read_text(encoding='utf-8')
    else:
        raw=subprocess.check_output(['wsl.exe','-d',DISTRO,'--exec','cat','/var/lib/dpkg/status'],encoding='utf-8')
    (OUT/'installed-dpkg-status.txt').write_text(raw,encoding='utf-8')
    wanted={}
    for pkg in records(raw):
        if pkg.get('Status')!='install ok installed':continue
        source=pkg.get('Source',pkg['Package'])
        match=re.fullmatch(r'(\S+)(?: \(([^)]+)\))?',source)
        name,version=match.group(1),match.group(2) or pkg['Version']
        wanted[(name,version)]=True
    lookup={(r['Package'],r['Version']):r for r in indexes}
    missing=[{'package':k[0],'version':k[1]} for k in wanted if k not in lookup]
    if missing:
        (OUT/'missing.json').write_text(json.dumps(missing,indent=2)+'\n')
        if not provisional:raise RuntimeError('Installed source versions absent from current indexes; see missing.json. Do not claim redistribution source closure.')
    files={}
    for key in wanted:
        if key not in lookup:continue
        r=lookup[key]
        for line in r['Checksums-Sha256'].splitlines():
            if not line.strip():continue
            checksum,size,name=line.split()
            files[name]=(r['Directory']+'/'+name,checksum,size)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        downloaded=list(pool.map(fetch_file,files.values()))
    result={'provisional':provisional,'missing':missing,
            'installedSnapshotSha256':hashlib.sha256(raw.encode()).hexdigest(),
            'packages':[{'source':k[0],'version':k[1]} for k in sorted(wanted)],'files':downloaded}
    (OUT/('provisional.json' if provisional else 'manifest.json')).write_text(json.dumps(result,indent=2)+'\n')
    if not missing:(OUT/'missing.json').unlink(missing_ok=True)
    print(f'Collected {len(downloaded)} source archives for {len(wanted)-len(missing)} source packages; missing {len(missing)}')

if __name__=='__main__':main()
