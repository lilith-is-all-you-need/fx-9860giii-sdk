"""Exercise the built probe and persistent files using the functional HLE."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

p=argparse.ArgumentParser()
p.add_argument('--bundle',type=Path,required=True)
p.add_argument('--emulator',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
bundle,exe,root=a.bundle.resolve(),a.emulator.resolve(),a.output.resolve()
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'emulator'))
from runtime_probe import Session
root.mkdir(parents=True,exist_ok=True)
results=[]

def prepare(name):
    folder=root/name
    storage=folder/'storage/fls0'
    storage.mkdir(parents=True,exist_ok=True)
    for name in ('Probe2.bin','Probe2.cfg'):(storage/name).write_bytes((bundle/name).read_bytes())
    return folder,storage

def log(storage):
    file=storage/'Probe2.txt'
    return file.read_text('ascii').rstrip() if file.exists() else ''

def wait(s,predicate):
    end=time.monotonic()+20
    while time.monotonic()<end:
        if predicate():return
        status=s.command('status')
        if status['state']=='error':raise AssertionError(status)
        time.sleep(.02)
    raise TimeoutError(s.command('status'))

def press(s,key):
    assert s.command('key',key=key,down=True)['ok']
    time.sleep(.06)
    assert s.command('key',key=key,down=False)['ok']

def start(folder,label,options=()):
    os.chdir(folder)
    s=Session(bundle/'Probe2.g1a',folder/label,options,executable=exe)
    s.remote.request('c',wait=False)
    return s

for mode in ('exit','menu'):
    folder,storage=prepare(mode)
    with start(folder,'first') as s:
        wait(s,lambda:'MENU_READY=' in log(storage))
        data=log(storage)
        assert data.count('PASS_CYCLE=')==8,data
        assert 'FAIL_' not in data,data
        assert 'AUTO_DONE=00000008,00000000' in data,data
        if mode=='menu':
            press(s,'MENU');wait(s,lambda:s.command('status')['osMenu'])
            assert s.command('menu-resume')['ok']
            press(s,'EXE');wait(s,lambda:'GETKEY_RESUMED=' in log(storage))
            press(s,'MENU');wait(s,lambda:s.command('status')['osMenu'])
            assert s.command('menu-replace')['ok']
        else:press(s,'EXIT')
        wait(s,lambda:s.command('status')['state']=='exited')
        data=log(storage)
        assert 'CALLBACK_CLEANED=00000000,00000001' in data,data
        assert data.count('PASS_TARGET_QUIT=')==9,data
        assert 'FAIL_' not in data,data
        if mode=='menu':assert 'CALLBACK_MAP_GUARD=00000000' in data,data
        else:assert 'EXIT_MAIN_RETURN' in data,data
    before=log(storage)
    with start(folder,'reentry') as s:
        wait(s,lambda:'REENTERED_NEW_STARTUP=' in log(storage))
        assert log(storage).startswith(before)
        assert 'CALLBACK_OBSERVED' in log(storage)
        press(s,'EXIT');wait(s,lambda:s.command('status')['state']=='exited')
        assert log(storage).count('PASS_CYCLE=')==8
    results.append({'case':mode+' + reentry','passed':True})

for mode in ('bad-config','bad-bin','no-bin','foreign-log','full-log','oom'):
    folder,storage=prepare(mode)
    original=None
    if mode=='bad-config':(storage/'Probe2.cfg').write_text('invalid\n')
    if mode=='bad-bin':
        data=bytearray((storage/'Probe2.bin').read_bytes());data[-1]^=1
        (storage/'Probe2.bin').write_bytes(data)
    if mode=='no-bin':(storage/'Probe2.bin').unlink()
    if mode=='foreign-log':original=b'keep this file'
    if mode=='full-log':original=b'FXPROBE2\n'+b'X'*(16384-9)
    if original is not None:(storage/'Probe2.txt').write_bytes(original)
    with start(folder,'run',['--heap-bytes','256'] if mode=='oom' else []) as s:
        wait(s,lambda:any(x.get('number')==0x90f for x in s.command('syscalls')['recent']))
        press(s,'EXIT');wait(s,lambda:s.command('status')['state']=='exited')
        if original is not None:assert (storage/'Probe2.txt').read_bytes()==original
        else:assert not (storage/'Probe2.txt').exists()
    results.append({'case':mode,'passed':True})

report={'hardwareVerified':False,'cases':results,
        'sha256':{n:hashlib.sha256((bundle/n).read_bytes()).hexdigest()
                  for n in ('Probe2.g1a','Probe2.bin','Probe2.cfg')}}
(root/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
