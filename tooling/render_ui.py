"""Render the app's own WPF tree; no screenshot fallback or synthetic UI state."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'src/FxStudio.App/bin/Debug/net10.0-windows/FxStudio.exe'
output = root / 'research/ui-editor.png'
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
subprocess.run([str(exe), '--project', str(root / 'examples/counter-cpp'), '--render-to', str(output)],
               startupinfo=startup, timeout=45, check=True)
assert output.is_file(), 'WPF did not produce the render'
print(output)
