"""Summarize a returned Probe3.txt; never interpret simulated evidence as hardware."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('report', type=Path)
p.add_argument('--origin', choices=['hardware', 'emulator', 'unknown'], default='unknown')
a = p.parse_args()
raw = a.report.read_bytes()
if not raw.startswith(b'FXPROBE3\n'):
    raise SystemExit('Not a Probe3 report; retain the original file for inspection')
lines = raw.decode('ascii').rstrip().splitlines()
values = {}
for line in lines:
    if '=' in line:
        name, value = line.split('=', 1)
        values.setdefault(name, []).append(value)
failures = [x for x in lines if x.startswith(('FAIL_', 'SKIP_'))]
failures += ['CALLBACK_RESTORED=' + x for x in values.get('CALLBACK_RESTORED', [])
             if not x.startswith('00000000,')]
checks = {
    'all512PagesCompared': len(values.get('PAGE', [])) == 512,
    'twoMappingCycles': len(values.get('PASS_MAP_CYCLE', [])) == 2,
    'afterFileOperation': 'PASS_AFTER_BFILE' in values,
    'ramShadowExecuted': 'PASS_SHADOW' in values,
    'automaticPhaseCompleted': 'AUTO_DONE' in values,
    'exitCallbackRestored': '00000000,00000001' in values.get('CALLBACK_RESTORED', []),
    'targetExitPageExecuted': '506701D6,00000000' in values.get('TARGET_QUIT_RESULT', []),
    'reentered': 'REENTERED' in values,
}
print(json.dumps({'origin': a.origin, 'complete': all(checks.values()) and not failures,
                  'checks': checks, 'failures': failures, 'lastLines': lines[-16:],
                  'meaning': 'Probe evidence only; not certification of KhiCAS or all OS behavior'},
                 ensure_ascii=False, indent=2))
