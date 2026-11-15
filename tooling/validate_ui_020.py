"""Run actual WPF debug handlers and render the real window without desktop capture."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
app, package = map(lambda p: Path(p).resolve(), sys.argv[1:3])
folder = Path('C:/fxstudio-build/ui-evidence-0.2.0')
folder.mkdir(parents=True, exist_ok=True)
project = folder / 'counter-cpp'
if not project.exists():
    shutil.copytree(root / 'examples/counter-cpp', project,
                    ignore=shutil.ignore_patterns('.fxstudio', 'project.fxide.json', 'build*'))
env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot'])/'System32'),
           HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
           DOTNET_ROOT=str(folder/'no-global-dotnet'), DOTNET_MULTILEVEL_LOOKUP='0')
records = []
for language in ('zh-CN','en'):
    render = folder / (language + '.png')
    error = Path(str(render)+'.error.txt')
    if error.exists():
        error.unlink()
    command = [str(app/'FxStudio.exe'), '--settings-dir', str(folder/('profile-'+language)),
               '--sdk', str(package/'sdk/native'), '--gdb', str(package/'runtime/gdb/bin/gdb.exe'),
               '--emulator', str(package/'runtime/emulator/FxEmulator.exe'),
               '--build-and-debug', str(project), '--render-break', 'main.cpp:49', '--render-to', str(render),
               '--verify-interactions', '--language', language]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(command, env=env, startupinfo=startup)
    try:
        code = process.wait(timeout=150)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'], capture_output=True)
        raise
    assert code == 0 and render.exists() and not error.exists(), error.read_text(encoding='utf8') if error.exists() else code
    record = json.loads(Path(str(render)+'.validation.json').read_text(encoding='utf8'))
    assert record['passed']
    record.update(language=language, render=str(render))
    records.append(record)
validation = dict(passed=True, checks=records, appSha256=hashlib.sha256((app/'FxStudio.dll').read_bytes()).hexdigest(),
                  application=str(app), package=str(package), hardwareTested=False,
                  desktopCapture='Actual WPF visual tree rendered and handlers exercised; this runner does not perform desktop capture.')
(root/'research/ui-0.2.0-validation.json').write_text(json.dumps(validation, indent=2), encoding='utf8')
print(json.dumps(validation, indent=2))
