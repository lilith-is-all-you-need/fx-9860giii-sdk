"""Compile real C/C++ G1A samples and verify symbols, flags and packaging."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distro',default='FxSDK-Dev-20261114')
    parser.add_argument('--output',type=Path,default=ROOT/'sdk/validation.json')
    parser.add_argument('--build-root',default='/tmp/fxide-smoke')
    args=parser.parse_args()
    def call(*cmd,**kw):
        return subprocess.run(['wsl.exe','-d',args.distro,'--exec',*map(str,cmd)],check=True,**kw)
    def read(path):
        return call('cat',path,capture_output=True,encoding='utf-8').stdout
    output=[]
    for example in ('hello-c','hello-cpp'):
        windows=ROOT/'sdk/examples'/example
        source=call('wslpath','-u',windows,capture_output=True,encoding='utf-8').stdout.strip()
        for mode in ('Debug','Release'):
            build=args.build_root+'/'+example+'-'+mode
            print(example,mode,flush=True)
            call('/opt/fxide/bin/build-project',source,build,mode)
            manifest=json.loads(read(build+'/artifact.json'))
            assert manifest['schemaVersion']==1 and manifest['configuration']==mode
            assert manifest['sourceMappings'][0]['to']==source
            assert 512<manifest['g1aBytes']<=2*1024*1024
            commands=[json.loads(line) for line in read(build+'/.fxide-compiler-commands.jsonl').splitlines()]
            assert commands,'No real compiler commands recorded'
            compiles=[x for x in commands if '-c' in x['arguments']]
            assert compiles,'No compilation occurred'
            for cmd in compiles:
                argv=cmd['arguments']
                if mode=='Debug':
                    assert '-Og' in argv and '-g3' in argv and '-fno-lto' in argv
                    assert not any(re.fullmatch(r'-O(?:[0-9]+|s|z|fast)',x) or x=='-flto' or x.startswith('-flto=') for x in argv)
                if example=='hello-cpp':assert '-fno-exceptions' in argv
            symbols=call('/root/.local/bin/sh-elf-nm','-C',manifest['elf'],capture_output=True,encoding='utf-8').stdout
            assert re.search(r'\b_main$',symbols,re.M),'main symbol missing'
            sections=call('/root/.local/bin/sh-elf-readelf','-SW',manifest['elf'],capture_output=True,encoding='utf-8').stdout
            if mode=='Debug':assert '.debug_info' in sections and '.symtab' in sections
            compile_db=json.loads(read(build+'/compile_commands.json'))
            assert compile_db and all('file' in row for row in compile_db)
            output.append({'example':example,'configuration':mode,'manifest':manifest,
                           'compileCount':len(compiles),'debugSymbols':'.debug_info' in sections})
    gdb=call('/usr/bin/gdb-multiarch','--version',capture_output=True,encoding='utf-8').stdout.splitlines()[0]
    # Ensure the shipped GDB actually understands the target ELF.
    debug_elf=output[0]['manifest']['elf']
    result=call('/usr/bin/gdb-multiarch','-q','-nx','-batch','-ex','set debuginfod enabled off',
                '-ex','file '+debug_elf,'-ex','info address main',capture_output=True,encoding='utf-8').stdout
    assert 'main' in result and '0x' in result
    report={'passed':True,'distro':args.distro,'gdb':gdb,'gdbSymbolProbe':result,'builds':output,
            'scope':'Real cross-compiled ELF/G1A and GDB symbols; calculator hardware not tested'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('All SDK smoke checks passed',flush=True)

if __name__=='__main__':main()
