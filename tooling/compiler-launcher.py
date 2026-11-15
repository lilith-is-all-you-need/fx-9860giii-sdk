#!/usr/bin/env python3
"""Execute the selected compiler, enforcing the IDE Debug profile last."""
import os
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

def debug_arguments(arguments):
    compile_only=any(flag in arguments for flag in ('-c','-S','-E','-fsyntax-only'))
    result=[]
    skip=False
    for index,arg in enumerate(arguments):
        if skip:
            skip=False
            continue
        if arg=='-Xlinker' and index+1<len(arguments) and arguments[index+1] in ('-s','--strip-all','--strip-debug'):
            skip=True
            continue
        if re.fullmatch(r'-O(?:[0-9]+|[sgz]|fast)?',arg): continue
        if arg in ('-flto','-fno-lto') or arg.startswith('-flto='): continue
        if arg in ('-fomit-frame-pointer','-g0','-s'): continue
        if arg.startswith('-Wl,'):
            flags=[x for x in arg[4:].split(',') if x not in ('-s','--strip-all','--strip-debug')]
            if not flags: continue
            arg='-Wl,'+','.join(flags)
        result.append(arg)
    # SDK archives include slim GCC 14.1 LTO objects. Disable LTO for the user's
    # source compilation, but let the final link read those prebuilt libraries.
    result += ['-Og','-g3','-fno-omit-frame-pointer', '-fno-lto' if compile_only else '-flto=auto']
    return result

def expand_response(arguments,depth=0):
    if depth>8: raise ValueError('Too many nested compiler response files')
    result=[]
    for arg in arguments:
        if arg.startswith('@'):
            result.extend(expand_response(shlex.split(Path(arg[1:]).read_text()),depth+1))
        else: result.append(arg)
    return result

if __name__=='__main__':
    args=sys.argv[1:]
    if not args: raise SystemExit('Missing compiler command')
    args=[args[0],*expand_response(args[1:])]
    is_cpp=Path(args[0]).name.removesuffix('.exe').endswith(('g++','c++')) or any(x.endswith(('.cpp','.cc','.cxx','.C')) for x in args[1:])
    if is_cpp:
        args=[x for x in args if x!='-fexceptions']+['-fno-exceptions']
    if os.environ.get('FXIDE_CONFIGURATION')=='Debug':
        args=[args[0],*debug_arguments(args[1:])]
    if os.environ.get('FXIDE_NATIVE')=='1' and not any(flag in args for flag in ('-c','-S','-E','-fsyntax-only')):
        # GCC 14.1 can copy zlib-compressed legacy SDK function bodies verbatim
        # into WPA partitions labelled with this host's default (zstd). A single
        # LTO partition avoids that incompatible intermediate representation.
        args=[x for x in args if not x.startswith('-flto-partition=')]+['-flto-partition=none']
    if path:=os.environ.get('FXIDE_COMMAND_LOG'):
        fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o644)
        try: os.write(fd,(json.dumps({'directory':os.getcwd(),'arguments':args})+'\n').encode())
        finally: os.close(fd)
    if os.name=='nt':
        raise SystemExit(subprocess.call(args))
    os.execvp(args[0],args)
