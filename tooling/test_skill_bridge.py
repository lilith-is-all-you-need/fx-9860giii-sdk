"""Exercise the shipped skill through separate CLI processes and a real SDK."""
from pathlib import Path
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'project'
    shutil.copytree(package / 'examples/counter-cpp', project,
                    ignore=shutil.ignore_patterns('.fxstudio', 'project.fxide.json', 'build*'))
    helper = ROOT / 'skills/fxstudio/scripts/fxstudio.py'
    python = package / 'sdk/native/host/python/python.exe'
    state, other = output / 'state', output / 'other-state'
    env = dict(os.environ, HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    checks = []

    def cli(*arguments, at=state, expected=0):
        result = subprocess.run([str(python), str(helper), '--package', str(package), '--state', str(at), *map(str, arguments)],
                                capture_output=True, text=True, encoding='utf8', timeout=60, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == expected, (arguments, result.returncode, result.stdout, result.stderr)
        return json.loads(result.stdout)

    def call(command, arguments, *, key=None, expected=0):
        path = output / ('args-' + uuid.uuid4().hex + '.json')
        # Exercise PowerShell-style BOM JSON and spaced/Unicode project paths.
        path.write_text(json.dumps(arguments), encoding='utf-8-sig')
        options = ['call', command, '--args-file', path]
        if key:
            options += ['--request-key', key]
        return cli(*options, expected=expected)

    def completed(reply, seconds=180):
        operation = reply['structuredContent']['operation']
        deadline = time.monotonic() + seconds
        while operation['status'] in ('queued', 'running'):
            assert time.monotonic() < deadline, operation
            reply = cli('operation', operation['operationId'])
            operation = reply['structuredContent']['operation']
        assert operation['status'] == 'succeeded', operation
        return operation

    try:
        assert cli('doctor')['package'] == str(package)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            starts = list(pool.map(lambda _: cli('start'), range(4)))
        assert len({s['hostId'] for s in starts}) == 1
        assert all(s['agentRunning'] for s in starts)
        checks.append('Four concurrent CLI starts share exactly one live host')
        second = cli('start', at=other)
        assert second['hostId'] != starts[0]['hostId']
        cli('stop', at=other)
        assert cli('status')['hostId'] == starts[0]['hostId']
        checks.append('Stopping a different state leaves this host running')

        info = json.loads((state / 'bridge.json').read_text(encoding='utf8'))
        try:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(f'http://127.0.0.1:{info["port"]}/rpc', data=b'{}'), timeout=5)
            raise AssertionError('Unauthenticated request was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        assert info['token'] not in json.dumps(starts)
        checks.append('Loopback requests require the token; CLI output omits it')

        catalog = cli('discover')['structuredContent']
        assert any(c['name'] == 'debug.key' for c in catalog['commands'])
        first = call('session.open', {'projectPath': str(project)}, key='open-once')
        opened = completed(first)
        duplicate = completed(call('session.open', {'projectPath': str(project)}, key='open-once'))
        assert duplicate['operationId'] == opened['operationId']
        conflict = call('session.open', {'projectPath': str(project.parent)}, key='open-once', expected=2)
        assert conflict['structuredContent']['error']['code'] == 'REQUEST_KEY_CONFLICT'
        session = opened['result']['sessionId']
        live = completed(call('session.list', {}))['result']['sessions']
        assert [s['sessionId'] for s in live] == [session]
        checks.append('Session survives CLI exits; retry deduplicates and conflicting keys fail')

        completed(call('build.run', {'sessionId': session, 'configuration': 'Debug'}))
        completed(call('debug.launch', {'sessionId': session, 'stopAt': 'main.cpp:49'}))
        before = completed(call('debug.snapshot', {'sessionId': session, 'expressions': ['counter.value']}))
        assert before['result']['expressions'][0]['value'] == '0', before
        completed(call('debug.resume', {'sessionId': session}))
        completed(call('debug.key', {'sessionId': session, 'key': 'PLUS', 'action': 'press'}))
        completed(call('debug.pause', {'sessionId': session}))
        after = completed(call('debug.snapshot', {'sessionId': session, 'expressions': ['counter.value']}))
        assert after['result']['expressions'][0]['value'] == '1', after
        screen = output / 'counter-one.png'
        cli('operation', after['operationId'], '--screen', screen)
        assert screen.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        assert cli('events', '--session', session)['structuredContent']['events']
        checks.append('Actual C++ build, breakpoint, PLUS input, counter=1, PNG and events')

        completed(call('debug.stop', {'sessionId': session}))
        release = completed(call('build.run', {'sessionId': session, 'configuration': 'Release'}))
        artifact = release['result']['artifact']
        assert Path(artifact['g1APath']).is_file(), artifact
        completed(call('session.close', {'sessionId': session}))
        assert completed(call('session.list', {}))['result']['sessions'] == []
        checks.append('Release G1A exists and owned session closes')
        cli('stop')
        assert not (state / 'bridge.json').exists()
        assert cli('status')['running'] is False
        checks.append('Host shutdown removes only its live descriptor')
        record = dict(passed=True, checks=checks, package=str(package), screen=str(screen),
                      artifact=artifact, hardwareTested=False)
        (output / 'validation.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf8')
        print(json.dumps(record, indent=2))
    finally:
        for directory in (state, other):
            if (directory / 'bridge.json').exists():
                cli('stop', at=directory)


if __name__ == '__main__':
    main()
