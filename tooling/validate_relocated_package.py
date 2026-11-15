"""Fresh-directory acceptance using only the portable runtime and Windows PATH."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
app, sdk = [Path(p).resolve() for p in sys.argv[1:3]]
destination = Path(r'C:\fxstudio-offline-check') / ("中文's install-" + time.strftime('%Y%m%d-%H%M%S'))
destination.mkdir(parents=True, exist_ok=False)
shutil.copytree(app, destination, dirs_exist_ok=True)
shutil.copytree(sdk, destination/'sdk/native')
shutil.copytree(ROOT/'dist-toolchain/native-gdb/runtime', destination/'runtime')
(destination/'runtime/emulator').mkdir()
shutil.copy2(ROOT/'probes/emulator/build/FxEmulator.exe', destination/'runtime/emulator/FxEmulator.exe')
for example in ('counter-c', 'counter-cpp'):
    shutil.copytree(ROOT/'examples'/example, destination/'examples'/example,
                    ignore=shutil.ignore_patterns('.fxstudio', 'project.fxide.json', 'build*'))
project = destination/"Projects/中文's project C++"
shutil.copytree(destination/'examples/counter-cpp', project)
env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot'])/'System32'),
           DOTNET_ROOT=str(destination/'no-global-dotnet'), DOTNET_MULTILEVEL_LOOKUP='0',
           HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9')
for variable in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'PYTHONPATH', 'PYTHONHOME'):
    env.pop(variable, None)
startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
render = destination/'ui-relocated.png'
args = [str(destination/'FxStudio.exe'), '--settings-dir', str(destination/'profile'), '--build-and-debug', str(project),
        '--render-to', str(render), '--render-break', 'main.cpp:49', '--language', 'en']
# No SDK/GDB/emulator overrides: the app must find its bundled components.
process = subprocess.Popen(args, env=env, startupinfo=startup)
try:
    result = process.wait(timeout=600)
except subprocess.TimeoutExpired:
    subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    raise
error = Path(str(render)+'.error.txt')
assert result == 0 and render.exists() and not error.exists(), error.read_text(encoding='utf8') if error.exists() else str(result)
checks = [{'name':'self-contained GUI + relocated native C++ Debug + default debugger/emulator discovery', 'passed':True}]
for example in ('counter-c', 'counter-cpp'):
    source = destination/'examples'/example
    output = source/'.fxstudio/build/Release'
    python = destination/'sdk/native/host/python/python.exe'
    service = destination/'sdk/native/service/build-native.py'
    log = destination/(example+'-Release.log')
    with log.open('w', encoding='utf8') as stream:
        done = subprocess.run([str(python), str(service), str(destination/'sdk/native'), str(source), str(output), 'Release'],
                              env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    assert done.returncode == 0, log.read_text(encoding='utf8')[-5000:]
    artifact = json.loads((output/'artifact.json').read_text(encoding='utf8'))
    assert artifact['artifactPair']['verified']
    checks.append({'name':'relocated '+example+' Release', 'passed':True, 'g1aBytes':artifact['g1aBytes'], 'sha256':artifact['sha256']})
record = {'passed':True, 'destination':str(destination), 'systemPathOnly':True, 'isolatedSettings':True,
          'noGlobalDotnet':True, 'noWslUsed':True, 'httpProxyRejectsConnections':True,
          'networkInterfaceDisabled':False, 'hardwareTested':False, 'unicodeInstallationPath':True, 'checks':checks}
(ROOT/'sdk/relocation-validation.json').write_text(json.dumps(record, indent=2), encoding='utf8')
shutil.copy2(render, ROOT/'research/ui-relocated-en.png')
print('PASS: relocated portable package, English GUI, Unicode project, C/C++ builds, debugger and screen')
print(destination)
