"""Actual native executables, Unicode paths, binary integrity and offline imports."""
import importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PREFIX=ROOT/'dist-toolchain/native-fxsdk/prefix'
WORK=ROOT/'dist-toolchain/native-fxsdk/tests/中文 路径'
WORK.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,PATH=str(Path(os.environ['SYSTEMROOT'])/'System32'),PYTHONUTF8='1')
checks=[]
def run(args,success=True):
    result=subprocess.run(list(map(str,args)),env=env,encoding='utf-8',errors='replace',capture_output=True)
    if success and result.returncode: raise RuntimeError(result.stdout+result.stderr)
    if not success and not result.returncode: raise RuntimeError('Invalid operation unexpectedly succeeded')
    return result
def checked(name): checks.append(name);print('PASS '+name)

original=ROOT/'probes/emulator/build/cas01.g1a'
elf=ROOT/'probes/emulator/build/cas-audit.elf'
payload=original.read_bytes()[512:]
binary=WORK/'测试 二进制.bin'
binary.write_bytes(payload)
output=WORK/'离线 输出.g1a'
icon=ROOT/'examples/counter-c/assets/icon.png'
run([PREFIX/'bin/fxgxa.exe','--g1a','--name=Test','--internal=@TEST','--date=2026.1114.1200','--icon='+str(icon),'-o',output,binary])
assert output.read_bytes()[512:]==payload
checked('Unicode paths and binary payload remain exact, including 0A bytes')
result=run([PREFIX/'bin/fxgxa.exe','--dump',output])
assert result.stdout.count('  OK ')==9,result.stdout
checked('All nine G1A header checks pass')
spec=importlib.util.spec_from_file_location('builder',ROOT/'tooling/build-project.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
assert builder.verify_artifact_pair(elf,output)['comparedBytes']==len(payload)
checked('Native packaging matches historical CAS01 ELF exactly')
extracted=WORK/'提取 图标.png'
run([PREFIX/'bin/fxgxa.exe','--extract','-o',extracted,output])
assert extracted.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
checked('Unicode libpng icon reading and writing')
run([PREFIX/'bin/fxgxa.exe','--dump',WORK/'absent.g1a'],False)
checked('Missing G1A fails cleanly')
run([PREFIX/'bin/fxgxa.exe','--g1a','--icon='+str(WORK/'absent.png'),'-o',output,binary],False)
run([PREFIX/'bin/fxgxa.exe','--g1a','-o',WORK/'absent-dir/output.g1a',binary],False)
checked('Missing PNG and unwritable output fail instead of reporting success')
assert 'sh3eb-elf/include' in run([PREFIX/'bin/fxsdk.exe','path','include']).stdout
checked('Unicode Python launcher and relative SDK discovery')
help_result=run([PREFIX/'bin/fxconv.exe','--help'])
assert 'usage: fxconv' in help_result.stdout+help_result.stderr
checked('fxconv loads with only Windows System32 on PATH')
assert run([PREFIX/'host/python/python.exe','-I','-c','from PIL import Image; import fxconv; print(Image.__version__)']).stdout.strip()=='11.3.0'
checked('Embedded Python and Pillow import without installed Python or site packages')
assert '3.31.8' in run([PREFIX/'host/cmake/bin/cmake.exe','--version']).stdout
assert '1.13.1' in run([PREFIX/'host/ninja/ninja.exe','--version']).stdout
checked('Portable CMake and Ninja launch with only System32 on PATH')
(WORK.parent/'host-test-results.json').write_text(json.dumps({'checks':checks,'count':len(checks)},indent=2)+'\n',encoding='utf-8')
