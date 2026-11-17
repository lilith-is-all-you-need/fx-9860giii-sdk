"""Build/debug the guarded starter through the existing skill/Agent API.
Requires a complete local SDK. Creates a new output directory and owns one host.
No physical calculator or upstream downloads are involved.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    helper = ROOT / 'skills/fxstudio/scripts/fxstudio.py'
    engineering = ROOT / 'skills/fxstudio/scripts/engineering.py'
    python = package / 'sdk/native/host/python/python.exe'
    state, project = output / 'state', output / 'project'
    subprocess.run([str(python), str(engineering), 'new', 'guarded-c', str(project)], check=True)
    snapshots = []

    def cli(*arguments):
        run = subprocess.run([str(python), str(helper), '--package', str(package),
                              '--state', str(state), *map(str, arguments)],
                             capture_output=True, text=True, encoding='utf8', timeout=60,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            raise RuntimeError(run.stdout + run.stderr)
        return json.loads(run.stdout)

    def call(command, arguments, timeout=240):
        argfile = output / 'arguments.json'
        argfile.write_text(json.dumps(arguments), encoding='utf8')
        reply = cli('call', command, '--args-file', argfile)
        op = reply['structuredContent']['operation']
        deadline = time.monotonic() + timeout
        while op['status'] in ('queued', 'running'):
            if time.monotonic() >= deadline:
                cli('operation', op['operationId'], '--cancel')
                raise TimeoutError('Requested cancellation: ' + command)
            time.sleep(0.1)
            reply = cli('operation', op['operationId'])
            op = reply['structuredContent']['operation']
        if op['status'] != 'succeeded':
            raise RuntimeError(json.dumps(op))
        return op

    session = None
    try:
        cli('doctor')
        cli('start')
        catalog = cli('discover')['structuredContent']
        (output / 'catalog.json').write_text(json.dumps(catalog, indent=2), encoding='utf8')
        commands = {entry['name'] for entry in catalog['commands']}
        required = {'session.open', 'build.run', 'debug.launch', 'debug.snapshot',
                    'debug.resume', 'debug.key', 'debug.pause', 'debug.stop', 'session.close'}
        if not required <= commands:
            raise RuntimeError('Runtime does not expose the required discovered commands')
        session = call('session.open', {'projectPath': str(project)})['result']['sessionId']
        print('Building guarded-c Debug through SDK', flush=True)
        debug = call('build.run', {'sessionId': session, 'configuration': 'Debug'})['result']['artifact']
        call('debug.launch', {'sessionId': session, 'stopAt': 'demo_ready'})
        expressions = ['selftest_failures', 'app.value', 'app.runs', 'scratch.used', 'last_status']

        def observe(label, expected):
            op = call('debug.snapshot', {'sessionId': session, 'include': ['screen'],
                                         'expressions': expressions})
            values = [entry['value'] for entry in op['result']['expressions']]
            if values != list(map(str, expected)):
                raise AssertionError((label, values, expected))
            snapshots.append({'label': label, 'expected': expected, 'result': op['result']})
            cli('operation', op['operationId'], '--screen', output / (label + '.png'))
            print(label + ': verified ' + ', '.join(values), flush=True)

        observe('startup', [0, 0, 0, 0, 0])
        for label, key, expected in (
            ('success', 'EXE', [0, 120, 1, 0, 0]),
            ('allocation-failure', 'F1', [0, 120, 1, 0, 1]),
            ('after-failure', 'EXE', [0, 120, 2, 0, 0]),
            ('cancellation', 'F2', [0, 120, 2, 0, 2]),
            ('after-cancellation', 'EXE', [0, 120, 3, 0, 0]),
            ('emulator-restart', 'EXIT', [0, 0, 0, 0, 0]),
        ):
            call('debug.resume', {'sessionId': session})
            call('debug.key', {'sessionId': session, 'key': key, 'action': 'press'})
            call('debug.pause', {'sessionId': session})
            observe(label, expected)
        call('debug.stop', {'sessionId': session})
        print('Building guarded-c Release through SDK', flush=True)
        release = call('build.run', {'sessionId': session, 'configuration': 'Release'})['result']['artifact']
        call('session.close', {'sessionId': session})
        session = None
        record = {'passed': True, 'debug': debug, 'release': release, 'snapshots': snapshots,
                  'hardwareTested': False,
                  'scope': 'Native SDK builds + real SuperH emulator contracts, key input and restart; not OS menu or device cache'}
        (output / 'validation.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf8')
        print(json.dumps({'passed': True, 'report': str(output / 'validation.json'),
                          'releaseG1a': release['g1APath'], 'hardwareTested': False}))
    finally:
        if (state / 'bridge.json').exists():
            if session:
                try:
                    call('session.close', {'sessionId': session}, timeout=30)
                except Exception:
                    pass
            cli('stop')


if __name__ == '__main__':
    main()
