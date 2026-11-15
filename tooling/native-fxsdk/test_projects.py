"""Build the shipped C/C++ examples through the real native service and run G1A."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
SDK=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'.codex-build-envs/native-sdk-20261114/prefix'
OUT=ROOT/'dist-toolchain/native-fxsdk/project-tests'
OUT.mkdir(parents=True,exist_ok=True)
ASCII=Path.home()/'.codex-build-envs/native-sdk-20261114/fxsdk-project-tests'
ASCII.mkdir(parents=True,exist_ok=True)
results=[]
try:
    for example in ('counter-c','counter-cpp'):
        for profile in ('Debug','Release'):
            key=example+'-'+profile
            output=OUT/key
            result=subprocess.run([sys.executable,str(ROOT/'tooling/build-native.py'),str(SDK),str(ROOT/'examples'/example),str(output),profile],capture_output=True,encoding='utf-8',errors='replace',timeout=180)
            (OUT/(key+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode: raise RuntimeError(key+' failed; see '+str(OUT/(key+'.log')))
            manifest=json.loads((output/'artifact.json').read_text(encoding='utf-8'))
            assert manifest['artifactPair']['verified']
            assert manifest['configuration']==profile
            if profile=='Debug':
                commandlog=Path(manifest['cacheDirectory'])/'build/.fxide-compiler-commands.jsonl'
                commands=[json.loads(line)['arguments'] for line in commandlog.read_text().splitlines()]
                compiles=[cmd for cmd in commands if '-c' in cmd]
                assert compiles and all('-Og' in cmd and '-g3' in cmd and '-fno-lto' in cmd for cmd in compiles)
                assert any('-flto=auto' in cmd and '-c' not in cmd for cmd in commands)
            addin=ASCII/(key+'.g1a')
            shutil.copy2(manifest['g1a'],addin)
            image=ASCII/(key+'.png')
            emulator=ROOT/'probes/emulator/build/preview-probe.exe'
            if emulator.is_file():
                preview=subprocess.run([str(emulator),str(addin),str(image),'PLUS,PLUS','3000'],cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace',timeout=35)
                (OUT/(key+'-preview.log')).write_text(preview.stdout+preview.stderr,encoding='utf-8')
                if preview.returncode: raise RuntimeError(key+' preview failed: '+preview.stdout+preview.stderr)
                state=json.loads(preview.stdout.split('PROBE_RESULT ',1)[1].splitlines()[0])
                assert state['saved'] and state['frames']>=1 and state['script_consumed']==state['script_steps']
                shutil.copy2(image,OUT/(key+'.png'))
            else: raise RuntimeError('Missing preview-probe.exe; do not claim native sample execution')
            results.append({'example':example,'configuration':profile,'g1aBytes':manifest['g1aBytes'],'pair':manifest['artifactPair'],'preview':state})
            print('PASS '+key+' native build, payload pair, and actual G1A execution')
finally:
    (OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
