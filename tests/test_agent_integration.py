"""Exercise the public MCP interface against a real native SuperH build/session."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tooling'))
from fxstudio_client import FxStudioClient


def result(reply):
    return reply['structuredContent']['operation']['result']


def check_png(encoded):
    data = base64.b64decode(encoded)
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    cursor, compressed, width, height = 8, b'', 0, 0
    while cursor < len(data):
        size = struct.unpack_from('>I', data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:cursor + 8 + size]
        assert zlib.crc32(kind + payload) == struct.unpack_from('>I', data, cursor + 8 + size)[0]
        if kind == b'IHDR':
            width, height, bits, color = struct.unpack_from('>IIBB', payload)
            assert (width, height, bits, color) == (128, 64, 8, 2)
        if kind == b'IDAT':
            compressed += payload
        cursor += size + 12
    pixels = zlib.decompress(compressed)
    assert len(pixels) == height * (1 + 3 * width)
    assert all(pixels[y * (1 + 3 * width)] == 0 for y in range(height))
    assert len(set(pixels)) > 2, 'Screen should contain drawn foreground and background'
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    evidence = ROOT / 'sdk/automation-validation.json'
    if evidence.exists():
        evidence.unlink()
    checks = []
    work = Path(tempfile.mkdtemp(prefix='FxStudio-agent-test-'))
    project = work / "中文's project"
    shutil.copytree(ROOT / 'examples/counter-cpp', project,
                    ignore=shutil.ignore_patterns('.fxstudio', 'project.fxide.json', 'build*'))
    # The launched service inherits only system PATH and rejects outbound HTTP.
    os.environ['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    os.environ['DOTNET_ROOT'] = str(work / 'no-global-dotnet')
    os.environ['DOTNET_MULTILEVEL_LOOKUP'] = '0'
    os.environ['HTTP_PROXY'] = os.environ['HTTPS_PROXY'] = os.environ['ALL_PROXY'] = 'http://127.0.0.1:9'
    for variable in ('PYTHONHOME', 'PYTHONPATH', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH'):
        os.environ.pop(variable, None)
    with FxStudioClient(args.agent, args.package) as client:
        tools = client.rpc('tools/list')['tools']
        assert {t['name'] for t in tools} == {'fxstudio_discover', 'fxstudio_execute', 'fxstudio_operation', 'fxstudio_events'}
        catalog = client.tool('fxstudio_discover')['structuredContent']
        assert catalog['contractVersion'] == '1.0'
        assert all(c['version'] == 1 and c['inputSchema']['additionalProperties'] is False for c in catalog['commands'])
        assert next(c for c in catalog['commands'] if c['name'] == 'debug.snapshot')['effect'] == 'read'
        checks.append('MCP initialization, stable four-tool interface and versioned schema discovery')
        submitted = {'command': 'session.open', 'arguments': {'projectPath': str(project)}, 'requestKey': 'open-once', 'waitMs': 1000}
        first = client.tool('fxstudio_execute', submitted)
        while first['structuredContent']['operation']['status'] not in ('succeeded', 'failed'):
            first = client.tool('fxstudio_operation', {'operationId': first['structuredContent']['operation']['operationId'], 'waitMs': 1000})
        session = result(first)['sessionId']
        again = client.tool('fxstudio_execute', submitted)
        assert first['structuredContent']['operation']['operationId'] == again['structuredContent']['operation']['operationId']
        conflict = client.tool('fxstudio_execute', dict(submitted, arguments={'projectPath': str(work)}))
        assert conflict['isError'] and conflict['structuredContent']['error']['code'] == 'REQUEST_KEY_CONFLICT'
        badversion = client.tool('fxstudio_execute', dict(submitted, version=99, requestKey='bad-version'))
        assert badversion['structuredContent']['error']['code'] == 'UNSUPPORTED_VERSION'
        checks.append('Retry deduplication, conflicting request key rejection and version rejection')

        def command(name, **arguments):
            return client.execute(name, {'sessionId': session, **arguments})

        def rejected(name, code=None, **arguments):
            response = client.tool('fxstudio_execute', {'command': name, 'arguments': {'sessionId': session, **arguments}, 'requestKey': uuid.uuid4().hex, 'waitMs': 1000})
            while 'operation' in response['structuredContent'] and response['structuredContent']['operation']['status'] in ('queued', 'running'):
                response = client.tool('fxstudio_operation', {'operationId': response['structuredContent']['operation']['operationId'], 'waitMs': 1000})
            assert response['isError'], response
            error = response['structuredContent'].get('error') or response['structuredContent']['operation']['error']
            if code:
                assert error['code'] == code, error
            return error

        rejected('debug.step', mode='into')
        rejected('project.inspect', unexpected=True, code='INVALID_ARGUMENT')
        inspected = result(command('project.inspect'))
        assert Path(inspected['session']['sourceDirectory']) == project
        checks.append('Structured precondition and unknown-argument errors; Unicode project inspection')
        built = result(command('build.run', configuration='Debug'))
        assert 'elf' in json.dumps(built).lower() and 'g1a' in json.dumps(built).lower()
        checks.append('Offline native C++ Debug build in a Unicode/apostrophe project directory')
        command('debug.launch', stopAt='main')
        main = result(command('debug.snapshot'))
        assert main['state'].lower() == 'stopped' and main['consistent']
        assert main['frames'][0]['function'] == 'main'
        assert main['registers'] and main['frames']
        checks.append('Verified ELF/G1A launched; real main source breakpoint, stack and registers')
        rejected('debug.snapshot', expressions=['counter.value = 123'])
        rejected('debug.variable.children', expression='clamp_counter(2)')
        command('debug.breakpoint.set', location='main.cpp:49', temporary=True)
        command('debug.resume')
        end = time.monotonic() + 15
        while time.monotonic() < end:
            shot = command('debug.snapshot', expressions=['counter.value', 'counter.updates'])
            if result(shot)['state'].lower() == 'stopped':
                break
            time.sleep(0.05)
        snapshot = result(shot)
        assert snapshot['consistent'] and snapshot['expressions'][0]['value'] == '0'
        assert snapshot['expressions'][1]['value'] == '0'
        image = next(x for x in shot['content'] if x['type'] == 'image')
        png = check_png(image['data'])
        (work / 'screen.png').write_bytes(png)
        bmp = Path(snapshot['screen']['path']).read_bytes()
        assert hashlib.sha256(bmp).hexdigest() == snapshot['screen']['sha256'].lower()
        checks.append('Stopped snapshot consistency, pure variable-path validation and real PNG screenshot')
        bp = result(command('debug.breakpoint.set', location='change_counter'))
        number = bp['number']
        command('debug.breakpoint.enabled', number=number, enabled=False)
        command('debug.breakpoint.enabled', number=number, enabled=True)
        command('debug.resume')
        live = result(command('debug.snapshot'))
        assert live['state'].lower() == 'running' and live['consistent'] is False and live['locals'] is None
        command('debug.key', key='PLUS', action='press')
        paused = result(command('debug.snapshot'))
        assert paused['state'].lower() == 'stopped' and 'change_counter' in paused['frames'][0]['function']
        checks.append('Breakpoint enable/disable, running snapshot semantics and real PLUS key hits function breakpoint')
        command('debug.step', mode='into')
        stepped = result(command('debug.snapshot'))
        assert stepped['consistent'] and stepped['revision'] > paused['revision']
        command('debug.step', mode='instruction')
        children = result(command('debug.variable.children', expression='counter'))
        assert {child['name'] for child in children['children']} == {'value', 'last_delta', 'updates'}, children
        mem = result(command('debug.memory.read', address='&counter', count=12))
        assert mem
        instructions = result(command('debug.disassemble', start='$pc', end='$pc+16'))
        assert instructions
        checks.append('Source and instruction stepping, structured members, memory and disassembly')
        command('debug.evaluate', expression='counter.value = 7')
        assert result(command('debug.snapshot', expressions=['counter.value']))['expressions'][0]['value'] == '7'
        rejected('debug.evaluate', expression='clamp_counter(2)', code='GDB_ERROR')
        assert result(command('debug.snapshot', expressions=['counter.value']))['expressions'][0]['value'] == '7'
        command('debug.breakpoint.remove', number=number)
        command('debug.resume')
        command('debug.pause')
        checks.append('Explicit target mutation, breakpoint removal, continue and pause')

        command('debug.resume')
        pending = client.tool('fxstudio_execute', {'command': 'debug.key', 'arguments': {'sessionId': session, 'key': 'PLUS', 'action': 'press', 'durationMs': 2000}, 'requestKey': 'cancel-key', 'waitMs': 0})
        operation_id = pending['structuredContent']['operation']['operationId']
        cancelled = client.tool('fxstudio_operation', {'operationId': operation_id, 'action': 'cancel', 'waitMs': 1000})
        while cancelled['structuredContent']['operation']['status'] in ('queued', 'running'):
            cancelled = client.tool('fxstudio_operation', {'operationId': operation_id, 'waitMs': 1000})
        assert cancelled['structuredContent']['operation']['status'] == 'cancelled'
        command('debug.pause')
        checks.append('Asynchronous operation cancellation leaves session usable')
        events = client.tool('fxstudio_events', {'after': 0, 'limit': 200})['structuredContent']
        assert events['events'] and all(e['sequence'] > 0 for e in events['events'])
        assert any(e['kind'] == 'operation.completed' for e in events['events'])
        command('session.close')
        sessions = result(client.execute('session.list'))
        assert session not in json.dumps(sessions)
        checks.append('Event journal cursors and explicit owned-session cleanup')
    assert client.process.returncode == 0, client.stderr
    checks.append('Clean stdio EOF shutdown')
    record = {'passed': True, 'checks': checks, 'workDirectory': str(work), 'agent': str(args.agent.resolve()),
              'package': str(args.package.resolve()), 'agentSha256': hashlib.sha256(args.agent.read_bytes()).hexdigest(),
              'binarySha256': {name: hashlib.sha256((args.agent.parent/name).read_bytes()).hexdigest()
                               for name in ('FxStudio.Agent.exe','FxStudio.Agent.dll','FxStudio.Automation.dll','FxStudio.Core.dll')},
              'systemPathOnly': True, 'noGlobalDotnet': True, 'httpProxyRejectsConnections': True,
              'networkInterfaceDisabled': False, 'hardwareTested': False}
    evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
