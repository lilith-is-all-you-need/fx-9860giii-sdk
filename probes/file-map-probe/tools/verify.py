"""Real SH Probe3 execution under firmware-assisted HLE; not hardware evidence."""
import argparse,json,shutil,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--firmware',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--stress',action='store_true');p.add_argument('--mode',choices=['exit','menu'],default='exit');p.add_argument('--timeout',type=float,default=300);a=p.parse_args()
root=a.output.resolve();root.mkdir(parents=True,exist_ok=False);store=root/'storage/fls0';store.mkdir(parents=True,exist_ok=True)
for name in ['Probe3.cfg','Probe3.bin','P3e4095.bin','P3e4096.bin','P3e4097.bin']:shutil.copy2(a.bundle/name,store/name)
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'emulator'))
from runtime_probe import Session
logpath=store/'Probe3.txt'
def log():return logpath.read_text('ascii').rstrip() if logpath.exists() else ''
def wait(s,condition):
 end=time.monotonic()+a.timeout
 while time.monotonic()<end:
  if condition():return
  status=s.command('status')
  if status['state'] in ('error','exited','rebooted'):raise AssertionError(status)
  if 'FAIL_' in log() or 'SKIP_' in log():raise AssertionError(log()[-2000:])
  time.sleep(.1)
 raise TimeoutError(s.command('status'))
def press(s,key):
 assert s.command('key',key=key,down=True)['ok'];time.sleep(.09);assert s.command('key',key=key,down=False)['ok']
options=['--os-firmware',a.firmware.resolve(),'--heap-bytes','49152','--trace-syscalls',root/'syscalls.jsonl']
if a.stress:options+=['--file-map-stress']
with Session(a.bundle.resolve()/'Probe3.g1a',root/'first',options,cwd=root) as s:
 s.remote.request('c',wait=False);wait(s,lambda:'MENU_PENDING' in log());time.sleep(.2)
 assert log().count('PAGE=')==512
 assert log().count('PASS_MAP_CYCLE=')==2
 assert 'PASS_SHADOW=' in log() and 'PASS_AFTER_BFILE=' in log()
 if a.mode=='menu':
  press(s,'MENU');wait(s,lambda:s.command('status')['osMenu']);assert s.command('menu-replace')['ok']
 else:press(s,'EXIT')
 wait(s,lambda:s.command('status')['state']=='exited')
 assert 'CALLBACK_RESTORED=00000000,00000001' in log(),log()[-1800:]
 assert 'FAIL_' not in log() and 'SKIP_' not in log(),log()[-1800:]
 if a.mode=='menu':assert 'TARGET_QUIT_RESULT=506701D6,00000000' in log(),log()[-1800:]
 status=s.command('status');diag=s.command('diagnostics')
reentry_options=list(options);reentry_options[reentry_options.index('--trace-syscalls')+1]=root/'reentry-syscalls.jsonl'
with Session(a.bundle.resolve()/'Probe3.g1a',root/'reentry',reentry_options,cwd=root) as s:
 s.remote.request('c',wait=False);wait(s,lambda:'REENTERED=' in log());press(s,'EXIT');wait(s,lambda:s.command('status')['state']=='exited')
result={'passed':True,'scope':__doc__,'firmware':str(a.firmware),'stress':a.stress,'mode':a.mode,'status':status,'diagnostics':diag,'log':str(logpath)}
(root/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
