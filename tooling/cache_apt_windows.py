"""Prefetch the clean SDK's Ubuntu packages using Windows, without starting WSL.

This is a download cache, not a replacement for APT's dependency solver. It
includes every available alternative in runtime dependency fields. Final APT
resolution and clean offline installation remain mandatory acceptance tests.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
from collect_distro_sources import records

ROOT=Path(__file__).resolve().parents[1]
FS=Path(os.environ['USERPROFILE'])/'.codex-build-envs/fxsdk-dev-20261114/rootfs'
CACHE=ROOT/'sdk/downloads'
INITIAL=('cmake','make','python3','python3-pil','libpng16-16t64','libusb-1.0-0',
         'zlib1g','gdb-multiarch','binutils','ca-certificates','git','xz-utils','unzip','pkg-config')

def version_key(v):
    epoch,_,rest=v.partition(':')
    return (int(epoch),rest) if _ else (0,v)

def compare_part(a,b):
    def order(c):
        if c=='~':return -1
        if not c:return 0
        return ord(c) if c.isalpha() else ord(c)+256
    while a or b:
        while (a and not a[0].isdigit()) or (b and not b[0].isdigit()):
            ac=a[0] if a and not a[0].isdigit() else ''
            bc=b[0] if b and not b[0].isdigit() else ''
            if order(ac)!=order(bc):return 1 if order(ac)>order(bc) else -1
            if ac:a=a[1:]
            if bc:b=b[1:]
        a=a.lstrip('0');b=b.lstrip('0')
        an=re.match(r'\d*',a).group();bn=re.match(r'\d*',b).group()
        if len(an)!=len(bn):return 1 if len(an)>len(bn) else -1
        if an!=bn:return 1 if an>bn else -1
        a=a[len(an):];b=b[len(bn):]
    return 0

def version_compare(a,b):
    ae,a=version_key(a);be,b=version_key(b)
    if ae!=be:return 1 if ae>be else -1
    au,sep,ar=a.rpartition('-');bu,sep2,br=b.rpartition('-')
    if not sep:au,ar=a,'0'
    if not sep2:bu,br=b,'0'
    return compare_part(au,bu) or compare_part(ar,br)

def download(pkg):
    name=pkg['Package']+'_'+pkg['Version'].replace(':','%3a')+'_'+pkg['Architecture']+'.deb'
    file=CACHE/name
    url='https://archive.ubuntu.com/ubuntu/'+pkg['Filename']
    def valid():
        if not file.is_file() or file.stat().st_size!=int(pkg['Size']):return False
        with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==pkg['SHA256']
    if not valid():
        for retry in range(3):
            try:
                with urllib.request.urlopen(url,timeout=120) as src,file.with_suffix('.deb.part').open('wb') as dst:
                    while chunk:=src.read(1024*1024):dst.write(chunk)
                file.with_suffix('.deb.part').replace(file)
                if not valid():raise ValueError('Package SHA256 mismatch: '+name)
                break
            except Exception:
                if retry==2:raise
    source=pkg.get('Source',pkg['Package'])
    match=re.fullmatch(r'(\S+)(?: \(([^)]+)\))?',source)
    return {'package':pkg['Package'],'version':pkg['Version'],'architecture':pkg['Architecture'],
            'file':name,'bytes':int(pkg['Size']),'sha256':pkg['SHA256'],'url':url,
            'source':match.group(1),'sourceVersion':match.group(2) or pkg['Version']}

def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    packages={};providers={}
    for index in (FS/'var/lib/apt/lists').glob('*_binary-amd64_Packages'):
        if 'noble-backports' in index.name:continue
        for pkg in records(index.read_text(encoding='utf-8')):
            name=pkg['Package']
            if name not in packages or version_compare(pkg['Version'],packages[name]['Version'])>0:packages[name]=pkg
    for name,pkg in packages.items():
        for provided in pkg.get('Provides','').split(','):
            virtual=provided.strip().split(' ')[0]
            if virtual:providers.setdefault(virtual,[]).append(name)
    installed={p['Package'] for p in records((FS/'var/lib/dpkg/status').read_text()) if p.get('Status')=='install ok installed'}
    wanted=set(INITIAL)|installed
    queue=list(wanted);missing=set()
    while queue:
        name=queue.pop()
        if name not in packages:
            options=providers.get(name,[])
            if not options:missing.add(name)
            for option in options:
                if option in installed or option==options[0]:
                    if option not in wanted:wanted.add(option);queue.append(option)
            continue
        pkg=packages[name]
        for dependency in re.split(r'[,|]',pkg.get('Pre-Depends','')+','+pkg.get('Depends','')):
            match=re.match(r'\s*([a-z0-9+.-]+)',dependency)
            if match:
                value=match.group(1)
                if value not in wanted:wanted.add(value);queue.append(value)
    chosen=[packages[name] for name in sorted(wanted) if name in packages]
    print('Prefetching binary package superset:',len(chosen),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:files=list(pool.map(download,chosen))
    result={'status':'downloaded; APT resolution and offline install not yet tested',
            'initial':list(INITIAL),'missingNames':sorted(missing),'files':files}
    (CACHE/'offline-cache-manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Cached',len(files),'packages; unresolved names:',sorted(missing),flush=True)

if __name__=='__main__':main()
