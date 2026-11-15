"""Verify refusal paths of the compiled Probe3 without a physical calculator."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bundle', type=Path, required=True)
p.add_argument('--firmware', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'emulator'))
from runtime_probe import Session

results = []
for case in ('missing-config', 'small-heap', 'foreign-log', 'unknown-os', 'wrong-hash'):
    root = a.output.resolve() / case
    storage = root / 'storage/fls0'
    storage.mkdir(parents=True, exist_ok=False)
    for name in ('Probe3.cfg', 'Probe3.bin', 'P3e4095.bin', 'P3e4096.bin', 'P3e4097.bin'):
        shutil.copy2(a.bundle / name, storage / name)
    trace = root / 'syscalls.jsonl'
    options = ['--heap-bytes', '4096' if case == 'small-heap' else '49152', '--trace-syscalls', trace]
    if case != 'unknown-os':
        options += ['--os-firmware', a.firmware.resolve()]
    output, expected = 'Probe3.txt', ''
    if case == 'missing-config':
        (storage / 'Probe3.cfg').unlink()
        output, expected = 'P3Start.txt', 'Check Probe3.cfg'
    elif case == 'small-heap':
        output, expected = 'P3Start.txt', 'Allocation failed'
    elif case == 'foreign-log':
        (storage / 'Probe3.txt').write_bytes(b'Unrelated user document\n')
    elif case == 'unknown-os':
        expected = 'SKIP_UNRECOGNIZED_OS'
    elif case == 'wrong-hash':
        cfg = storage / 'Probe3.cfg'
        cfg.write_text(cfg.read_text().replace('FD8125E1', '00000000'), newline='\n')
        expected = 'FAIL_PREFLIGHT'
    with Session(a.bundle.resolve() / 'Probe3.g1a', root / 'run', options, cwd=root) as s:
        s.remote.request('c', wait=False)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            report = (storage / output).read_text('ascii') if (storage / output).exists() else ''
            state = s.command('status')
            assert state['state'] not in ('error', 'exited', 'rebooted'), state
            if (expected and expected in report) or (case == 'foreign-log' and trace.exists() and 'GetKey' in trace.read_text()):
                break
            time.sleep(.1)
        else:
            raise TimeoutError(case)
        assert 'MAP_CYCLE_PENDING' not in report
        s.command('key', key='EXIT', down=True)
        time.sleep(.1)
        s.command('key', key='EXIT', down=False)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and s.command('status')['state'] != 'exited':
            time.sleep(.05)
        assert s.command('status')['state'] == 'exited', s.command('status')
        if case == 'foreign-log':
            assert (storage / 'Probe3.txt').read_bytes() == b'Unrelated user document\n'
        if case == 'wrong-hash':
            assert 'FAIL_BIN_HASH' in report
    results.append({'case': case, 'passed': True})
(a.output / 'verification.json').write_text(json.dumps(results, indent=2), encoding='utf8')
print(json.dumps(results))
