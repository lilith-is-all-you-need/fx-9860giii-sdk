"""Exercise the launcher as a process, including response files and C++ policy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

LAUNCHER=Path(__file__).with_name('compiler-launcher.py')

with tempfile.TemporaryDirectory(prefix='fxide launcher ') as temp:
    root=Path(temp)
    recorder=root/'record.py'
    recorder.write_text('import json,sys; print(json.dumps(sys.argv[1:]))\n')
    response=root/'options.rsp'
    response.write_text('-c -Os -flto=auto -fexceptions -fomit-frame-pointer -Wl,-s,--gc-sections -Xlinker --strip-debug sample.cpp')
    env=dict(os.environ,FXIDE_CONFIGURATION='Debug',FXIDE_COMMAND_LOG=str(root/'commands.jsonl'))
    result=subprocess.check_output([sys.executable,str(LAUNCHER),sys.executable,str(recorder),'@'+str(response)],env=env,text=True)
    args=json.loads(result)
    assert all(flag in args for flag in ('-Og','-g3','-fno-lto','-fno-omit-frame-pointer','-fno-exceptions'))
    assert all(flag not in args for flag in ('-Os','-flto=auto','-fexceptions','-fomit-frame-pointer','--strip-debug','-Xlinker'))
    assert '-Wl,--gc-sections' in args
    logged=json.loads((root/'commands.jsonl').read_text())
    assert logged['arguments'][2:]==args
    linked=json.loads(subprocess.check_output([sys.executable,str(LAUNCHER),sys.executable,str(recorder),'-fno-lto','-Os','sample.o','-lgint'],env=env,text=True))
    assert '-flto=auto' in linked and '-fno-lto' not in linked and '-Os' not in linked
    env['FXIDE_CONFIGURATION']='Release'
    result=subprocess.check_output([sys.executable,str(LAUNCHER),sys.executable,str(recorder),'-O3','-flto','sample.c'],env=env,text=True)
    assert json.loads(result)==['-O3','-flto','sample.c']
    env['FXIDE_NATIVE']='1'
    linked=json.loads(subprocess.check_output([sys.executable,str(LAUNCHER),sys.executable,str(recorder),'-O3','-flto-partition=balanced','sample.o'],env=env,text=True))
    assert '-flto-partition=none' in linked and '-flto-partition=balanced' not in linked
print('Compiler launcher process checks passed')
