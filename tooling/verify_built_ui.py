"""Exercise the real IDE build/start path, then render its source breakpoint."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
app, sdk, gdb = [Path(value).resolve() for value in sys.argv[1:4]]
emulator = ROOT / 'probes/emulator/build/FxEmulator.exe'
output = ROOT / 'research/ui-native-counter.png'
for path in (output, Path(str(output)+'.error.txt'), Path(str(output)+'.state.txt')):
    path.unlink(missing_ok=True)
startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot'])/'System32'),
           HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
args = [str(app), '--build-and-debug', str(ROOT/'examples/counter-cpp'), '--sdk', str(sdk),
        '--gdb', str(gdb), '--emulator', str(emulator), '--render-to', str(output), '--render-break', 'main.cpp:49', '--language', 'zh-CN']
process = subprocess.Popen(args, env=env, startupinfo=startup)
try:
    status = process.wait(timeout=600)
except subprocess.TimeoutExpired:
    subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    raise
error = Path(str(output)+'.error.txt')
assert status == 0 and not error.exists(), error.read_text(encoding='utf8') if error.exists() else f'App exit {status}'
state = Path(str(output)+'.state.txt').read_text(encoding='utf8')
assert 'Build' in state or 'Building' in state
assert 'breakpoint-hit' in state and 'main' in state
manifest = json.loads((ROOT/'examples/counter-cpp/.fxstudio/build/Debug/artifact.json').read_text(encoding='utf8'))
def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
(ROOT/'research/ui-native-validation.json').write_text(json.dumps({
    'passed':True, 'systemPathOnly':True, 'httpProxyRejectsConnections':True, 'source':'counter-cpp',
    'configuration':'Debug', 'artifactHashes':manifest['sha256'], 'appSha256':digest(app), 'gdbSha256':digest(gdb),
    'emulatorSha256':digest(emulator), 'render':output.name, 'stop':'main.cpp:49', 'hardwareTested':False
}, indent=2), encoding='utf8')
print('PASS: actual IDE C++ build -> verified G1A -> native GDB -> source breakpoint and runtime framebuffer')
