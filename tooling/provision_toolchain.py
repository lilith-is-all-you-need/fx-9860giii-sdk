"""Provision only the explicitly named clean WSL development distribution.

Run on Windows. Reads selected public toolchain/package metadata from the source
distribution; never exports its root filesystem or writes to it.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = 'FxSDK-Dev-20261114'
SOURCE = 'Ubuntu-24.04'
CACHE = ROOT / 'sdk' / 'downloads'
PACKAGES = ['cmake', 'make', 'python3', 'python3-pil', 'libpng16-16t64',
            'libusb-1.0-0', 'zlib1g', 'gdb-multiarch', 'binutils',
            'ca-certificates', 'git', 'xz-utils', 'unzip', 'pkg-config']

def wsl(distro, *args, **kw):
    return subprocess.run(['wsl.exe', '-d', distro, '--exec', *map(str,args)], check=True, **kw)

def transfer(paths):
    assert DEST != SOURCE
    reader = subprocess.Popen(['wsl.exe','-d',SOURCE,'--exec','tar','-C','/', '-cpf','-', *paths], stdout=subprocess.PIPE)
    writer = subprocess.Popen(['wsl.exe','-d',DEST,'--exec','tar','-C','/', '-xpf','-'], stdin=reader.stdout)
    reader.stdout.close()
    if writer.wait() or reader.wait():
        raise RuntimeError('Public toolchain transfer failed')

def download(entry):
    url, name, size, algorithm, checksum = entry
    file = CACHE / name
    algorithm = {'MD5Sum':'md5', 'SHA256':'sha256'}.get(algorithm,algorithm.lower())
    def valid():
        return file.is_file() and file.stat().st_size == int(size) and hashlib.new(algorithm, file.read_bytes()).hexdigest() == checksum
    existing = Path(r'\\wsl.localhost\Ubuntu-24.04\var\cache\apt\archives') / name
    if not valid() and existing.is_file():
        shutil.copyfile(existing,file)
    if not valid():
        url = url.replace('http://', 'https://', 1)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=90) as stream, file.with_suffix(file.suffix+'.part').open('wb') as out:
                    while chunk := stream.read(1024*1024):
                        out.write(chunk)
                file.with_suffix(file.suffix+'.part').replace(file)
                if not valid():
                    raise ValueError('Checksum mismatch for '+name)
                break
            except Exception as error:
                if attempt == 2:
                    raise RuntimeError(f'{name}: {error}; {url}') from error
    return {'url':url,'file':name,'bytes':file.stat().st_size,
            'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}

def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    if 'transfer' in sys.argv:
        transfer(['root/.local/bin','root/.local/include','root/.local/lib','root/.local/share/fxsdk',
                  'var/lib/apt/lists'])
    result = wsl(DEST, 'apt-get','--print-uris','--yes','--no-install-recommends','install',*PACKAGES,
                 capture_output=True,text=True)
    (CACHE/'apt-plan.txt').write_text(result.stdout,encoding='utf-8')
    entries = re.findall(r"^'([^']+)' (\S+) (\d+) (\w+):([0-9a-f]+)$",result.stdout,re.M)
    print('Packages to download:',len(entries),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(download,entries))
    (CACHE/'manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    linux_cache = wsl(DEST,'wslpath','-u',CACHE,capture_output=True,text=True).stdout.strip()
    wsl(DEST,'cp','-t','/var/cache/apt/archives',*[linux_cache+'/'+e[1] for e in entries])
    wsl(DEST,'env','DEBIAN_FRONTEND=noninteractive','apt-get','--no-download','--yes','--no-install-recommends','install',*PACKAGES)

if __name__ == '__main__':
    main()
