"""Run the packaged static GDB against the real Windows SuperH emulator."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'dist-toolchain/native-gdb/verification'
BASE=ROOT/'probes/emulator/build'
GDB=ROOT/'dist-toolchain/native-gdb/runtime/gdb/bin/gdb.exe'
ENV=dict(os.environ,PATH=str(Path(os.environ['WINDIR'])/'System32'),PYTHONHOME='',PYTHONPATH='')

def run_case(name,g1a,commands):
    frame=OUT/(name+'.bmp');frame.unlink(missing_ok=True)
    with (OUT/(name+'-emulator.log')).open('w',encoding='utf-8') as stderr:
        emulator=subprocess.Popen([str(BASE/'FxEmulator.exe'),'--gdb-port','0','--control-port','0',
                                   '--framebuffer',str(frame),str(BASE/g1a)],
                                  stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf-8',cwd=OUT)
        try:
            ready_queue=queue.Queue()
            threading.Thread(target=lambda:ready_queue.put(emulator.stdout.readline()),daemon=True).start()
            ready=json.loads(ready_queue.get(timeout=10))
            arguments=[str(GDB),'-nx','-batch']
            initial=['set pagination off','set confirm off','set architecture sh4al-dsp','set endian big']
            for command in initial+[f'target remote 127.0.0.1:{ready["gdbPort"]}']+commands:
                arguments+=['-ex',command]
            result=subprocess.run(arguments,env=ENV,cwd=OUT,capture_output=True,
                                  encoding='utf-8',errors='replace',timeout=40)
            log=result.stdout+result.stderr
            (OUT/(name+'-gdb.log')).write_text(log,encoding='utf-8')
            if result.returncode:raise RuntimeError(name+' failed: '+log)
            return log,frame
        finally:
            if emulator.poll() is None:
                emulator.terminate();emulator.wait(timeout=5)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    lowlevel=[
        'info registers r0 r15 pc pr sr','x/4i $pc','stepi','info registers pc',
        'set $r0=42','print $r0','set {unsigned int}0x08102000=1234','x/wx 0x08102000',
        'set {unsigned short}0x08101000=0xe001','set {unsigned short}0x08101002=0xe102',
        'set $pc=0x08101000','break *0x08101002','continue','delete breakpoints',
        'set {unsigned short}0x08101004=0x2202','set {unsigned short}0x08101006=0x6322',
        'set {unsigned short}0x08101008=0x7001','set {unsigned short}0x0810100a=0xaffb',
        'set {unsigned short}0x0810100c=0x0009','set $r2=0x08102000','set $pc=0x08101000',
        'watch *(int*)0x08102000','continue','print *(int*)0x08102000','delete breakpoints',
        'rwatch *(int*)0x08102000','continue','print $r3','delete breakpoints',
        'break *0x08101004 if $r0==3','continue','print $r0','delete breakpoints','detach','quit']
    log,_=run_case('machine','cas02.g1a',lowlevel)
    assert '$1 = 42' in log and '0x000004d2' in log and 'Breakpoint 1,' in log
    assert 'Hardware watchpoint' in log and 'Hardware read watchpoint' in log and '$4 = 3' in log
    path=(BASE/'cas-audit.elf').as_posix()
    directory=(BASE/'cas01-source/src').as_posix()
    commands=[f'file "{path}"',f'directory "{directory}"','break main','continue',
              'print key_options','backtrace','next','break ui_draw','continue',
              'info args','print ui->input[0]','print ui->notice','backtrace','next','step',
              'delete breakpoints','echo === FINISH ===\n','finish','backtrace','detach','quit']
    log,frame=run_case('source','cas01.g1a',commands)
    assert 'Breakpoint 1, main' in log and 'ui_draw' in log and 'Starting CAS' in log
    assert '#0  main' in log.split('=== FINISH ===')[1]
    assert frame.is_file() and frame.stat().st_size>1024
    data=frame.read_bytes()
    assert data[:2]==b'BM' and int.from_bytes(data[18:22],'little')==128
    assert abs(int.from_bytes(data[22:26],'little',signed=True))==64
    report={'passed':True,'gdbSha256':hashlib.sha256(GDB.read_bytes()).hexdigest(),
            'checks':['register read/write','instruction single-step','memory read/write',
                      'software breakpoint','conditional breakpoint','write watchpoint','read watchpoint',
                      'source breakpoint','locals/arguments','call stack','source next/step/finish',
                      'paused framebuffer','Chinese/apostrophe path','System32-only PATH'],
            'fixture':'CAS01 exact ELF/G1A pair for source debugging; CAS02 for machine operations',
            'hardwareTested':False}
    (OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
