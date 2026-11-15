"""Package and verify the native SuperH GDB using only Windows system DLLs."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from embed_manifest import embed

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'dist-toolchain/native-gdb'
SCRATCH=Path(os.environ['USERPROFILE'])/'.codex-build-envs/native-gdb-20261114'
RUNTIME=OUT/'runtime/gdb'
BIN=RUNTIME/'bin'
SYSTEM_DLLS={'advapi32.dll','bcrypt.dll','crypt32.dll','gdi32.dll','iphlpapi.dll',
             'kernel32.dll','msvcrt.dll','ntdll.dll','ole32.dll','oleaut32.dll',
             'psapi.dll','rpcrt4.dll','secur32.dll','shell32.dll','shlwapi.dll',
             'user32.dll','userenv.dll','version.dll','winmm.dll','ws2_32.dll','dbghelp.dll'}

def digest(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    source=SCRATCH/'prefix/bin/sh-elf-gdb.exe'
    if not source.is_file():raise RuntimeError('Native GDB has not been built and installed')
    BIN.mkdir(parents=True,exist_ok=True)
    stripped=SCRATCH/'gdb-stripped.exe';shutil.copy2(source,stripped)
    subprocess.run(['C:/msys64/mingw64/bin/strip.exe','--strip-unneeded',str(stripped)],check=True)
    embed(stripped,HERE/'utf8.manifest')
    target=BIN/'gdb.exe';shutil.copy2(stripped,target)
    shared=SCRATCH/'prefix/share/gdb'
    if shared.is_dir():shutil.copytree(shared,RUNTIME/'share/gdb',dirs_exist_ok=True)
    imports=subprocess.check_output(['C:/msys64/mingw64/bin/objdump.exe','-p',str(stripped)],text=True)
    dlls=re.findall(r'DLL Name:\s*(\S+)',imports)
    unexpected=[name for name in dlls if name.lower() not in SYSTEM_DLLS and not name.lower().startswith('api-ms-win-')]
    if unexpected:raise RuntimeError('Native GDB still depends on non-system DLLs: '+str(unexpected))
    env=dict(os.environ,PATH=str(Path(os.environ['WINDIR'])/'System32'),PYTHONHOME='',PYTHONPATH='')
    version=subprocess.check_output([str(target),'--version'],env=env,encoding='utf-8',errors='replace')
    config=subprocess.check_output([str(target),'-q','-nx','-batch','-ex','show configuration',
                                    '-ex','set architecture sh4','-ex','show architecture'],env=env,encoding='utf-8',errors='replace')
    assert '16.3' in version and '--without-python' in config and '--target=sh-elf' in config
    elf=ROOT/'probes/emulator/build/cas-audit.elf'
    probe=None
    if elf.is_file():
        command=[str(target),'-q','-nx','-batch','-se',str(elf),'-ex','info files','-ex','info address main']
        result=subprocess.run(command,env=env,capture_output=True,encoding='utf-8',errors='replace')
        if result.returncode or 'elf32-sh' not in result.stdout:
            raise RuntimeError('SuperH ELF probe failed: '+result.stdout+result.stderr)
        probe={'elfSha256':digest(elf),'output':result.stdout,'stderr':result.stderr}
    licenses=OUT/'licenses';licenses.mkdir(exist_ok=True)
    for path in (SCRATCH/'source/gdb-16.3').glob('COPYING*'):
        shutil.copy2(path,licenses/('gdb-'+path.name))
    shutil.copy2(HERE/'build.sh',OUT/'build.sh')
    for name in ('relink.sh','utf8.manifest','embed_manifest.py','patch_source.py','run_build.py','package.py','rebuild.py'):
        shutil.copy2(HERE/name,OUT/name)
    for name in ('configure.log','build.log','install.log','relink.log','reinstall.log'):
        shutil.copy2(SCRATCH/name,OUT/name)
    manifest={'schemaVersion':1,'name':'GNU GDB for SuperH, native Windows',
              'version':'16.3','host':'x86_64-w64-mingw32','target':'sh-elf',
              'executable':'runtime/gdb/bin/gdb.exe','bytes':target.stat().st_size,
              'sha256':digest(target),'systemDlls':dlls,'externalDlls':unexpected,
              'python':False,'guile':False,'requiresWsl':False,
              'configuration':config,'elfProbe':probe,
              'sources':['source-manifest.json','dependency-manifest.json'],
              'validation':'Starts with Windows System32-only PATH and loads SuperH ELF'}
    (OUT/'native-gdb-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    checks=[]
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name!='SHA256SUMS.txt':checks.append(f'{digest(p)}  {p.relative_to(OUT).as_posix()}\n')
    (OUT/'SHA256SUMS.txt').write_text(''.join(checks),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
