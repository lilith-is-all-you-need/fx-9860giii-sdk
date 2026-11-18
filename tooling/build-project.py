#!/usr/bin/env python3
"""Build a trusted fxSDK CMake project without editing its source directory.

Usage: /opt/fxide/bin/build-project SOURCE BUILD Debug|Release
Output: BUILD/artifact.json (schemaVersion 1) only after a successful build.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import struct
import sys
import time
import uuid

SDK=Path('/root/.local')
MODULES=SDK/'lib/cmake/fxsdk'
LAUNCHER=str(Path(__file__).with_name('compiler-launcher' + Path(__file__).suffix))
IGNORED={'.git','.vs','.idea','__pycache__','.fxide-source','.fxstudio','CMakeFiles'}

def run(args,env,**kwargs):
    print('+ '+' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),env=env,check=True,**kwargs)

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def contained_path(path,root,label):
    """Resolve aliases before any output deletion or write."""
    resolved=path.resolve()
    boundary=root.resolve()
    if resolved==boundary or not resolved.is_relative_to(boundary):
        raise RuntimeError(f'{label} must remain inside {boundary}: {path}')
    return resolved

def remove_staged(path,stage):
    # Removing a managed symlink removes only the link; its target is untouched.
    if path.parent!=stage: contained_path(path.parent,stage,'Staging parent')
    if path.is_symlink():
        path.unlink()
        return
    path=contained_path(path,stage,'Staged path')
    if path.is_dir(): shutil.rmtree(path)
    else: path.unlink(missing_ok=True)

def sync_source(source,stage,build):
    marker=stage/'.fxide-managed'
    if stage.is_symlink() or stage.is_junction(): raise RuntimeError('Source staging directory must not be a symlink or junction')
    if marker.is_symlink(): raise RuntimeError('Source staging marker must not be a symlink')
    if stage.exists() and not marker.is_file():
        raise RuntimeError('Refusing to modify an unmanaged source staging directory')
    stage.mkdir(exist_ok=True)
    marker.write_text('Source staging owned by FXIDE\n')
    expected={marker}
    for parent,dirs,files in os.walk(source):
        current=Path(parent)
        dirs[:]=[d for d in dirs if d not in IGNORED and (current/d).resolve()!=build
                 and not (current/d/'CMakeCache.txt').is_file()]
        for name in dirs:
            if (current/name).is_symlink() or (current/name).is_junction():
                raise RuntimeError(f'Directory symlinks/junctions are not supported in source staging: {current/name}')
        relative=current.relative_to(source)
        dest=stage/relative
        if dest!=stage:
            if dest.is_symlink() or (dest.exists() and not dest.is_dir()): remove_staged(dest,stage)
            contained_path(dest,stage,'Staging directory')
        dest.mkdir(parents=True,exist_ok=True)
        expected.add(dest)
        for name in files:
            if name in ('CMakeCache.txt','artifact.json','.fxide-build.pid','.fxide-build.lock','.fxide-managed'):
                continue
            src=current/name
            dst=dest/name
            if not src.is_file():
                raise RuntimeError(f'Source file is broken or not a regular file: {src}')
            if dst.is_symlink() or (dst.exists() and not dst.is_file()): remove_staged(dst,stage)
            contained_path(dst,stage,'Staged file')
            expected.add(dst)
            # Metadata alone cannot certify that current source was staged.
            if not dst.is_file() or src.stat().st_size!=dst.stat().st_size or digest(src)!=digest(dst):
                shutil.copy2(src,dst)
    for item in sorted(stage.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if item in expected: continue
        remove_staged(item,stage)

def select_target(build,preferred,validate=True):
    replies=build/'.cmake/api/v1/reply'
    indexes=sorted(replies.glob('index-*.json'),key=lambda p:p.stat().st_mtime_ns)
    if not indexes: raise RuntimeError('CMake did not provide its executable target metadata')
    index=json.loads(indexes[-1].read_text())
    codemodel=json.loads((replies/index['reply']['codemodel-v2']['jsonFile']).read_text())
    targets=[]
    for cfg in codemodel['configurations']:
        for entry in cfg['targets']:
            target=json.loads((replies/entry['jsonFile']).read_text())
            if target['type']=='EXECUTABLE' and (not preferred or target['name']==preferred):
                targets.append(target)
    if len(targets)!=1:
        raise RuntimeError('Expected one executable target; select target in fxide.json for a multi-target project')
    target=targets[0]
    elf=contained_path(build/target['artifacts'][0]['path'],build,'Executable target')
    if validate and elf.read_bytes()[:4]!=b'\x7fELF': raise RuntimeError('Target output is not ELF')
    return target['name'],elf

def verify_artifact_pair(elf_path,g1a_path):
    """Check that this linked ELF is exactly the packaged G1A, without Core."""
    if elf_path.stat().st_size>512*1024*1024: raise RuntimeError('ELF exceeds 512 MiB inspection limit')
    if not 512<g1a_path.stat().st_size<=2_000_000: raise RuntimeError('G1A size is outside the supported range (maximum 2,000,000 bytes)')
    elf=elf_path.read_bytes()
    g1a=g1a_path.read_bytes()
    if len(elf)<52 or elf[:7]!=b'\x7fELF\x01\x02\x01':
        raise RuntimeError('Expected a version-1 big-endian ELF32 file')
    header=struct.unpack('>16sHHIIIIIHHHHHH',elf[:52])
    if header[1]!=2 or header[2]!=42 or header[3]!=1 or header[8]!=52:
        raise RuntimeError('Expected a linked SuperH ELF32 executable')
    if header[4]!=0x00300200: raise RuntimeError('ELF entry does not match the G1A entry at 0x00300200')
    ghead=bytes(x^255 for x in g1a[:32])
    u32=lambda data,offset: int.from_bytes(data[offset:offset+4],'big')
    if ghead[:9]!=b'USBPower\xf3' or ghead[9:14]!=bytes([0,16,0,16,0]) or ghead[15]!=1:
        raise RuntimeError('Invalid G1A fixed header bytes')
    if u32(ghead,16)!=len(g1a) or u32(g1a,0x1f0)!=len(g1a):
        raise RuntimeError('G1A header file size does not match the file')
    if ghead[14]!=((len(g1a)+0x41)&255) or ghead[20]!=((len(g1a)+0xb8)&255):
        raise RuntimeError('Invalid G1A size control bytes')
    checksum=sum(int.from_bytes(g1a[i:i+2].ljust(2,b'\0'),'big') for i in range(0x300,0x310,2))&65535
    if int.from_bytes(ghead[22:24],'big')!=checksum: raise RuntimeError('Invalid G1A header checksum')
    phoff,phsize,phcount=header[5],header[9],header[10]
    if phoff<52 or phsize<32 or phcount in (0,65535) or phoff+phsize*phcount>len(elf):
        raise RuntimeError('ELF program header table is invalid or truncated')
    payload=g1a[512:]
    covered=bytearray(len(payload))
    segments=[]
    for number in range(phcount):
        at=phoff+number*phsize
        kind,offset,vaddr,paddr,filesz,memsz,flags,align=struct.unpack('>IIIIIIII',elf[at:at+32])
        if kind!=1: continue
        if filesz>memsz or offset+filesz>len(elf) or vaddr+memsz>2**32 or paddr+filesz>2**32:
            raise RuntimeError(f'ELF PT_LOAD {number} has invalid size or bounds')
        if align>1 and (align&(align-1) or vaddr%align!=offset%align):
            raise RuntimeError(f'ELF PT_LOAD {number} has invalid alignment')
        if not filesz: continue
        start=paddr-0x00300200
        end=start+filesz
        if start<0 or end>len(payload): raise RuntimeError(f'ELF PT_LOAD {number} lies outside the G1A payload')
        if any(covered[start:end]): raise RuntimeError('ELF ROM load segments overlap')
        if elf[offset:offset+filesz]!=payload[start:end]:
            raise RuntimeError(f'ELF/G1A payload mismatch in PT_LOAD {number} at LMA 0x{paddr:08X}')
        covered[start:end]=b'\x01'*filesz
        segments.append({'loadAddress':paddr,'fileBytes':filesz,'payloadOffset':start})
    if not segments or min(s['payloadOffset'] for s in segments)!=0 or max(s['payloadOffset']+s['fileBytes'] for s in segments)!=len(payload):
        raise RuntimeError('ELF ROM extent does not match the G1A payload extent')
    if any(byte and not covered[i] for i,byte in enumerate(payload)):
        raise RuntimeError('G1A has nonzero data outside the ELF ROM load segments')
    return {'verified':True,'payloadBytes':len(payload),'comparedBytes':sum(covered),'segments':segments}

def main():
    import fcntl  # Execution is Linux-only; pure helpers are testable on Windows.
    if len(sys.argv)!=4 or sys.argv[3] not in ('Debug','Release'):
        raise SystemExit('Usage: build-project SOURCE BUILD Debug|Release')
    source=Path(sys.argv[1]).resolve()
    build=Path(sys.argv[2]).resolve()
    configuration=sys.argv[3]
    if not (source/'CMakeLists.txt').is_file(): raise RuntimeError('Source has no CMakeLists.txt')
    if source==build or source.is_relative_to(build): raise RuntimeError('Build directory must not contain the source directory')
    build.mkdir(parents=True,exist_ok=True)
    lock=(build/'.fxide-build.lock').open('a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('A build is already running in this directory')
    if os.getpid()!=os.getpgrp(): os.setsid()
    elif os.getsid(0)!=os.getpid():
        raise RuntimeError('Cannot create an isolated build session')
    pid=os.getpid()
    start_time=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    pidfile=build/'.fxide-build.pid'
    nonce=uuid.uuid4().hex
    pidfile.write_text(json.dumps({'pid':pid,'startTime':start_time,'nonce':nonce,'buildDirectory':str(build)}))
    artifact=build/'artifact.json'
    artifact.unlink(missing_ok=True)
    try:
        stage=build/'.fxide-source'
        sync_source(source,stage,build)
        config=json.loads((stage/'fxide.json').read_text()) if (stage/'fxide.json').is_file() else {}
        query=build/'.cmake/api/v1/query'
        query.mkdir(parents=True,exist_ok=True)
        (query/'codemodel-v2').touch()
        env=dict(os.environ,PATH=str(SDK/'bin')+':/usr/local/bin:/usr/bin:/bin',
                 FXIDE_CONFIGURATION=configuration,LC_ALL='C.UTF-8',PYTHONUTF8='1',
                 FXIDE_COMMAND_LOG=str(build/'.fxide-compiler-commands.jsonl'))
        (build/'.fxide-compiler-commands.jsonl').unlink(missing_ok=True)
        options=[f'-DCMAKE_TOOLCHAIN_FILE={MODULES}/FX9860G.cmake',
                 f'-DCMAKE_MODULE_PATH={MODULES}',f'-DFXSDK_CMAKE_MODULE_PATH={MODULES}',
                 f'-DCMAKE_BUILD_TYPE={configuration}','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                 f'-DCMAKE_C_COMPILER_LAUNCHER={LAUNCHER}',f'-DCMAKE_CXX_COMPILER_LAUNCHER={LAUNCHER}',
                 f'-DCMAKE_C_LINKER_LAUNCHER={LAUNCHER}',f'-DCMAKE_CXX_LINKER_LAUNCHER={LAUNCHER}']
        # User CMake options are structured strings, never passed through a shell.
        for key,value in config.get('cmake',{}).items():
            if not isinstance(key,str) or not key.replace('_','').isalnum(): raise RuntimeError('Invalid CMake option name')
            if key.startswith('CMAKE_') or key.startswith('FXSDK_'): raise RuntimeError('Toolchain CMake options are managed by the IDE')
            options.append(f'-D{key}={value}')
        # Copying source changes custom generated outputs; force the executable
        # target link after configure so each build regenerates its G1A.
        run(['cmake','-S',stage,'-B',build,*options],env)
        before={str(p):p.stat().st_mtime_ns for root in (stage,build) for p in root.rglob('*.g1a') if '.fxide-source' not in p.relative_to(root).parts or root==stage}
        name,old_elf=select_target(build,config.get('target'),validate=False)
        old_elf.unlink(missing_ok=True)
        run(['cmake','--build',build,'--target',name,'--parallel',str(min(os.cpu_count() or 2,8))],env)
        name,elf=select_target(build,config.get('target'))
        if configuration=='Debug':
            sections=subprocess.check_output([str(SDK/'bin/sh-elf-readelf'),'-SW',str(elf)],env=env,text=True)
            if '.debug_info' not in sections or '.symtab' not in sections:
                raise RuntimeError('Debug ELF has no debug information or symbol table; a custom build step may have stripped it')
        changed=[]
        for root in (stage,build):
            for p in root.rglob('*.g1a'):
                if root==build and '.fxide-source' in p.relative_to(root).parts: continue
                if before.get(str(p))!=p.stat().st_mtime_ns: changed.append(p)
        if len(changed)!=1:
            raise RuntimeError(f'Expected exactly one newly generated G1A, found {len(changed)}')
        g1a=contained_path(changed[0],build,'Generated G1A')
        if g1a.stat().st_size>2_000_000:
            raise RuntimeError('G1A exceeds the conservative 2,000,000-byte deployment budget')
        header=subprocess.check_output([str(SDK/'bin/fxgxa'),'-d',str(g1a)],env=env,text=True)
        if header.count('  OK ')!=9: raise RuntimeError('G1A header validation failed: '+header)
        out=contained_path(build/'artifacts',build,'Artifact directory')
        out.mkdir(exist_ok=True)
        final_elf=contained_path(out/(name+'.elf'),build,'Published ELF')
        final_g1a=contained_path(out/(name+'.g1a'),build,'Published G1A')
        if elf!=final_elf: shutil.copy2(elf,final_elf)
        if g1a!=final_g1a: shutil.copy2(g1a,final_g1a)
        pairing=verify_artifact_pair(final_elf,final_g1a)
        mapping={'from':str(stage),'to':str(source)}
        manifest={'schemaVersion':1,'elf':str(final_elf),'g1a':str(final_g1a),
                  'sourceDirectory':str(source),'buildDirectory':str(build),
                  'sourceMappings':[mapping],'configuration':configuration,'target':name,
                  'debugFlagsForced':configuration=='Debug',
                  'artifactPair':pairing,
                  'sha256':{'elf':digest(final_elf),'g1a':digest(final_g1a)},
                  'g1aBytes':final_g1a.stat().st_size,
                  'capabilities':{'cppExceptions':False,'cppThreads':False},
                  'hardwareVerified':False,'toolchain':'fxSDK 2.11.0 / GCC 14.1.0 / gint 2.11.0'}
        (build/'artifact.json.tmp').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        (build/'artifact.json.tmp').replace(artifact)
        print(json.dumps(manifest,ensure_ascii=False),flush=True)
    finally:
        if pidfile.exists() and json.loads(pidfile.read_text()).get('nonce')==nonce: pidfile.unlink()

if __name__=='__main__':
    try: main()
    except (RuntimeError,subprocess.CalledProcessError) as error:
        print('Build failed: '+str(error),file=sys.stderr)
        raise SystemExit(1)
