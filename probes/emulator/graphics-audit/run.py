"""Audit the actual 0.1.1 package without editing it. All results stay here."""
from pathlib import Path
import hashlib, json, os, shutil, socket, subprocess, sys
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACKAGE = ROOT/'dist-windows/FxStudio-0.1.1-win-x64'
SDK = PACKAGE/'sdk/native'
PYTHON = SDK/'host/python/python.exe'
OUT = HERE/'results'
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE.parent))
import test_native_examples as support
support.GDB = PACKAGE/'runtime/gdb/bin/gdb.exe'
MI = support.MI
ENV = dict(os.environ, PATH=str(Path(os.environ['SYSTEMROOT'])/'System32'), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')

if '--reuse-build' not in sys.argv:
    subprocess.run([str(PYTHON), '-B', str(HERE/'prepare_assets.py')], check=True, env=ENV)
    build = subprocess.run([str(PYTHON), str(SDK/'service/build-native.py'), str(SDK),
        str(HERE), str(OUT/'build'), 'Debug'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', env=ENV, timeout=180)
    (OUT/'build.log').write_text(build.stdout+build.stderr, encoding='utf-8')
    if build.returncode: raise RuntimeError('Build failed; see results/build.log')
manifest = json.loads((OUT/'build/artifact.json').read_text(encoding='utf-8'))
assert manifest['artifactPair']['verified']
# GDB symbols are staged in ASCII only; the package and input project remain Unicode.
WORK = Path.home()/'.codex-build-envs/graphics-audit-20261115'
WORK.mkdir(exist_ok=True)
for extension in ('elf', 'g1a'):
    shutil.copy2(manifest[extension], WORK/('probe.'+extension))
frame = WORK/'screen.bmp'
frame.unlink(missing_ok=True)
emuexe = PACKAGE/'runtime/emulator/FxEmulator.exe'
stderr = (OUT/'emulator.log').open('w', encoding='utf-8')
emulator = subprocess.Popen([str(emuexe), '--gdb-port', '0', '--control-port', '0',
    '--framebuffer', str(frame), str(WORK/'probe.g1a')], cwd=WORK, env=ENV,
    stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8')
mi = control = stream = None
evidence = {'package': str(PACKAGE), 'passed': False, 'stops': []}
try:
    ready = json.loads(emulator.stdout.readline())
    control = socket.create_connection(('127.0.0.1', ready['controlPort']), timeout=5)
    stream = control.makefile('rwb')
    def ctrl(command):
        stream.write((json.dumps(command)+'\n').encode()); stream.flush()
        reply = json.loads(stream.readline()); assert reply['ok'], reply
        return reply
    mi = MI(WORK/'probe.elf', WORK)
    for cmd in ('-gdb-set pagination off', '-gdb-set confirm off', '-gdb-set mi-async on',
                '-gdb-set architecture sh4al-dsp', '-gdb-set endian big'):
        mi.command(cmd)
    mi.command('-target-select remote 127.0.0.1:'+str(ready['gdbPort']))
    for function in ('audit_mono_ready', 'audit_gray_ready', 'audit_off_ready'):
        mi.command('-break-insert '+function)
    for phase in ('mono', 'gray', 'off'):
        stopped = mi.advance('-exec-continue')
        assert 'audit_'+phase+'_ready' in stopped, stopped
        status = ctrl({'command': 'status'})
        assert status['state'] == 'paused' and not status.get('error'), status
        assert len(set(support.pixels(frame))) > 1
        output = OUT/(phase+'.bmp'); shutil.copy2(frame, output)
        evidence['stops'].append({'phase': phase, 'status': status})
        if phase == 'mono':
            evidence['graphicsChecks'] = int(mi.value('graphics_checks'), 0)
            assert evidence['graphicsChecks'] == 127, evidence
        if phase == 'gray':
            evidence['grayStartResult'] = int(mi.value('gray_start_result'), 0)
            assert evidence['grayStartResult'] == 0, evidence
            data = output.read_bytes(); offset = int.from_bytes(data[10:14], 'little')
            def sample(x, y):
                p = offset+(63-y)*384+x*3
                return list(data[p:p+3])
            samples = [sample(x, 30) for x in (16,48,80,112)]
            evidence['shadeSamplesBgr'] = samples
            assert len({tuple(v) for v in samples}) == 4, samples
            assert all(sum(samples[i]) > sum(samples[i+1]) for i in range(3)), samples
    evidence.update(passed=True, artifactPair=manifest['artifactPair'],
        artifactSha256=manifest['sha256'],
        emulatorSha256=hashlib.sha256(emuexe.read_bytes()).hexdigest())
    mi.command('-target-detach')
    try:
        ctrl({'command': 'quit'})
        evidence['shutdownReply'] = 'ok'
    except (ConnectionResetError, json.JSONDecodeError) as error:
        # Keep a transport issue visible without conflating it with graphics checks.
        evidence['shutdownReply'] = type(error).__name__+': '+str(error)
    evidence['emulatorExitCode'] = emulator.wait(timeout=5)
    assert evidence['emulatorExitCode'] == 0
finally:
    if mi:
        mi.close(); (OUT/'gdb-mi.log').write_text('\n'.join(mi.log)+'\n', encoding='utf-8')
    if stream: stream.close()
    if control: control.close()
    if emulator.poll() is None: emulator.terminate()
    emulator.wait(timeout=5); stderr.close()
    (OUT/'results.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
print(json.dumps(evidence, indent=2))
