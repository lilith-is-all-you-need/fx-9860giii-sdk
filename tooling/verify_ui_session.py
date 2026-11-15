"""Capture the real WPF view at a real source breakpoint; requires no WSL."""
from pathlib import Path
import json
import hashlib
import os
import subprocess
import sys

historical_source_root = os.environ.get('FXSTUDIO_HISTORICAL_SOURCE_ROOT')
if not historical_source_root:
    raise SystemExit('This optional historical-fixture probe requires private local CAS01 fixtures. '
                     'Set FXSTUDIO_HISTORICAL_SOURCE_ROOT to their original DWARF source root. '
                     'Use tooling/validate_ui_020.py for the public example-based validation.')

root = Path(__file__).resolve().parents[1]
fixture = root / 'probes/emulator/build'
evidence = root / 'research'
descriptor = evidence / 'cas01-local.fxdebug.json'
pair = json.loads((fixture / 'cas01-pairing.json').read_text())
descriptor.write_text(json.dumps({
    'schemaVersion': 1, 'name': 'CAS01 · verified historical build',
    'elf': '../probes/emulator/build/cas-audit.elf', 'g1a': '../probes/emulator/build/cas01.g1a',
    'sourceDirectory': '../probes/emulator/build/cas01-source',
    'elfSha256': pair['elfSha256'], 'g1aSha256': pair['g1aSha256'],
    'sourceMappings': [{
        'from': historical_source_root,
        'to': '../probes/emulator/build/cas01-source'}]
}, indent=2), encoding='utf8')
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'C:\fxstudio-build\publish\FxStudio.exe')
gdb = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r'C:\msys64\mingw64\bin\gdb-multiarch.exe')
output = evidence / 'ui-debug.png'
for path in (output, Path(str(output) + '.state.txt'), Path(str(output) + '.error.txt')):
    path.unlink(missing_ok=True)
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
result = subprocess.run([str(exe), '--debug-build', str(descriptor), '--gdb', str(gdb),
    '--emulator', str(fixture / 'FxEmulator.exe'), '--render-to', str(output),
    '--render-break', 'main.c:78'], startupinfo=startup, timeout=90)
assert result.returncode == 0, f'Application exited {result.returncode}'
error = Path(str(output) + '.error.txt')
assert not error.exists(), error.read_text() if error.exists() else ''
assert output.exists(), 'No render produced'
state = Path(str(output) + '.state.txt').read_text(encoding='utf8')
assert 'breakpoint-hit' in state and 'main' in state, state
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
(evidence / 'ui-session-validation.json').write_text(json.dumps({
    'passed': True, 'fixture': 'CAS01 historical verified pair',
    'appSha256': digest(exe), 'gdbSha256': digest(gdb),
    'emulatorSha256': digest(fixture / 'FxEmulator.exe'),
    'elfSha256': pair['elfSha256'], 'g1aSha256': pair['g1aSha256'],
    'screen': output.name, 'stop': 'main.c:78', 'hardwareTested': False
}, indent=2), encoding='utf8')
print('PASS: real WPF source pause, source mapping, debugger inspectors and framebuffer render')
