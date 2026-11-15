"""Freeze the dedicated public SDK distribution after successful smoke tests."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist-toolchain'
DISTRO='FxSDK-Dev-20261114'

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(*args,**kwargs):
    return subprocess.run(['wsl.exe','-d',DISTRO,'--exec',*map(str,args)],check=True,**kwargs)

def main():
    for path in (OUT/'sources/sdk/manifest.json',OUT/'sources/ubuntu/manifest.json',ROOT/'sdk/validation.json'):
        if not path.is_file():raise RuntimeError('Missing required source or validation manifest: '+str(path))
    validation=json.loads((ROOT/'sdk/validation.json').read_text())
    if not validation.get('passed'):raise RuntimeError('SDK smoke tests have not passed')
    (OUT/'install').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'tooling/Install-OfflineSdk.ps1',OUT/'install/Install-OfflineSdk.ps1')
    shutil.copytree(ROOT/'sdk/examples',OUT/'examples',dirs_exist_ok=True)
    shutil.copy2(ROOT/'sdk/BUILD-SERVICE.md',OUT/'BUILD-SERVICE.md')
    shutil.copy2(ROOT/'sdk/validation.json',OUT/'validation.json')
    # Include build-service implementation and source gathering/packaging scripts.
    shutil.copytree(ROOT/'tooling',OUT/'sources/fxide-tooling',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    licensing=OUT/'licenses';licensing.mkdir(exist_ok=True)
    # Standard distro copyright files identify every included dependency. Read
    # only the public documentation directory, never a personal home directory.
    stream=subprocess.Popen(['wsl.exe','-d',DISTRO,'--exec','tar','-C','/usr/share/doc','-czf','-','.'],stdout=subprocess.PIPE)
    with (licensing/'ubuntu-package-documents.tar.gz').open('wb') as dest:
        shutil.copyfileobj(stream.stdout,dest,1024*1024)
    if stream.wait():raise RuntimeError('License documentation export failed')
    raw=OUT/'fxsdk-dev-rootfs.tar'
    packed=OUT/'fxsdk-dev-rootfs.tar.gz'
    subprocess.run(['wsl.exe','--export',DISTRO,str(raw)],check=True)
    with raw.open('rb') as source,packed.open('wb') as dest:
        with gzip.GzipFile(filename='',fileobj=dest,mode='wb',mtime=0,compresslevel=6) as compressor:
            shutil.copyfileobj(source,compressor,1024*1024)
    # raw was created above at a fixed path in our output directory.
    if raw.parent.resolve()!=OUT.resolve():raise RuntimeError('Unexpected export path')
    raw.unlink()
    manifest={'schemaVersion':1,'name':'FX SDK Offline Development Toolchain','distro':DISTRO,
              'architecture':'x86_64','wslVersion':1,
              'rootfs':{'file':packed.name,'bytes':packed.stat().st_size,'sha256':digest(packed)},
              'versions':{'gcc':'14.1.0','binutils':'2.42','fxsdk':'2.11.0','gint':'2.11.0'},
              'buildEntry':'/opt/fxide/bin/build-project','cancelEntry':'/opt/fxide/bin/cancel-build',
              'gdb':'/usr/bin/gdb-multiarch','sources':['sources/sdk/manifest.json','sources/ubuntu/manifest.json'],
              'capabilities':{'c':True,'cpp':True,'cppExceptions':False,'cppThreads':False},
              'hardwareVerified':False}
    (OUT/'toolchain-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    checks=[]
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name!='SHA256SUMS.txt':
            checks.append(f'{digest(p)}  {p.relative_to(OUT).as_posix()}\n')
    (OUT/'SHA256SUMS.txt').write_text(''.join(checks),encoding='utf-8')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
