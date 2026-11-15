"""Local CLI bridge to the bundled Fx Studio MCP client; Python stdlib only."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BYTES = 1_048_576
REQUIRED = ('FxStudio.Agent.exe', 'automation/fxstudio_client.py',
            'sdk/native/host/python/python.exe', 'sdk/native/service/build-native.py',
            'runtime/gdb/bin/gdb.exe', 'runtime/emulator/FxEmulator.exe')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    os.replace(temporary, path)


def package_path(explicit=None):
    selected = explicit or os.environ.get('FXSTUDIO_PACKAGE')
    if selected:
        choices = [Path(selected).resolve()]
    else:
        choices = []
        for anchor in (Path.cwd(), Path(__file__).resolve().parent):
            for parent in (anchor, *anchor.parents):
                choices.append(parent)
                versions = sorted((parent / 'dist-windows').glob('FxStudio-*-win-x64'),
                                  key=lambda p: tuple(int(n) if n.isdigit() else 0
                                                      for n in p.name.split('-')[1].split('.')),
                                  reverse=True)
                choices.extend(versions)
    for candidate in choices:
        if all((candidate / name).is_file() for name in REQUIRED):
            return candidate
    raise RuntimeError('Complete SDK package not found. Pass --package DIR or set FXSTUDIO_PACKAGE. '
                       'A Git source checkout alone is not the offline SDK.')


def descriptor(state):
    value = load_json(state / 'bridge.json')
    if value.get('schemaVersion') != 1 or not isinstance(value.get('port'), int):
        raise RuntimeError('Invalid bridge state; use a new --state directory.')
    return value


def request(info, payload, timeout=20):
    data = json.dumps(payload).encode('utf8')
    if len(data) > MAX_BYTES:
        raise ValueError('Bridge request exceeds 1 MiB.')
    req = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/rpc', data=data,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + info['token']})
    # Ignore proxies. A lost local response can be retried against this exact
    # host/token: execute carries the same requestKey, other actions are idempotent.
    for attempt in range(3):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.1 * (attempt + 1))
    if 'bridgeError' in result:
        raise RuntimeError(result['bridgeError'])
    return result


def alive(state):
    try:
        info = descriptor(state)
        result = request(info, {'action': 'status'}, timeout=2)
        return info if result.get('hostId') == info.get('hostId') else None
    except (OSError, ValueError, KeyError, RuntimeError):
        return None


@contextlib.contextmanager
def host_lock(state):
    """The live worker owns this OS lock; concurrent starts cannot replace it."""
    import msvcrt
    with (state / 'host.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def client_class(package):
    spec = importlib.util.spec_from_file_location('fxstudio_bundled_client', package / 'automation/fxstudio_client.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FxStudioClient


def serve(state, package, idle_seconds):
    if os.name != 'nt':
        raise RuntimeError('Fx Studio requires Windows x64.')
    state.mkdir(parents=True, exist_ok=True)
    with host_lock(state):
        host_id, token = uuid.uuid4().hex, secrets.token_hex(32)
        client = client_class(package)(package / 'FxStudio.Agent.exe', package)
        activity = [time.monotonic()]
        closing = threading.Event()
        # Serialize individual MCP requests. Long builds remain asynchronous in Agent.
        gate = threading.Lock()
        metadata = dict(hostId=host_id, pid=os.getpid(), package=str(package),
                        state=str(state), idleSeconds=idle_seconds)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                if self.path != '/rpc' or not hmac.compare_digest(
                        self.headers.get('Authorization', ''), 'Bearer ' + token):
                    self.send_error(403)
                    return
                if self.headers.get('Content-Type') != 'application/json':
                    self.send_error(415)
                    return
                try:
                    size = int(self.headers.get('Content-Length', '-1'))
                    if not 0 <= size <= MAX_BYTES:
                        raise ValueError('Invalid request length.')
                    self.connection.settimeout(10)
                    payload = json.loads(self.rfile.read(size))
                    with gate:
                        if closing.is_set():
                            raise RuntimeError('Host is stopping.')
                        activity[0] = time.monotonic()
                        action = payload.get('action')
                        if action == 'status':
                            result = dict(metadata, agentRunning=client.process.poll() is None)
                        elif action == 'stop':
                            closing.set()
                            result = dict(metadata, stopping=True)
                        elif action == 'tool' and payload.get('name') in (
                                'fxstudio_discover', 'fxstudio_execute', 'fxstudio_operation', 'fxstudio_events'):
                            result = client.tool(payload['name'], payload.get('arguments', {}))
                        else:
                            raise ValueError('Unknown bridge action/tool.')
                except Exception as error:
                    result = {'bridgeError': str(error)}
                body = json.dumps(result).encode('utf8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        class Server(ThreadingHTTPServer):
            # Several simultaneous CLI starts each probe readiness before use.
            request_queue_size = 64

        server = Server(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        server.timeout = 0.5
        info = dict(metadata, schemaVersion=1, port=server.server_port, token=token)
        atomic_json(state / 'bridge.json', info)
        try:
            while not closing.is_set() and client.process.poll() is None:
                if time.monotonic() - activity[0] >= idle_seconds:
                    break
                server.handle_request()
        finally:
            closing.set()
            server.server_close()
            with gate:
                client.close()
            try:
                if descriptor(state)['hostId'] == host_id:
                    (state / 'bridge.json').unlink()
            except (OSError, ValueError, KeyError):
                pass


def ensure_host(state, selected, idle_seconds):
    selected = selected or os.environ.get('FXSTUDIO_PACKAGE')
    info = alive(state)
    if info:
        if selected and Path(info['package']).resolve() != package_path(selected):
            raise RuntimeError('This state directory belongs to another package. Use a different --state.')
        return info
    package = package_path(selected)
    if os.name != 'nt':
        raise RuntimeError('Fx Studio requires Windows x64.')
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'bridge.log').open('ab') as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--state', str(state),
                          '--package', str(package), '--idle-seconds', str(idle_seconds), '_serve'],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if info := alive(state):
            if Path(info['package']).resolve() != package:
                raise RuntimeError('A concurrent host selected another package. Use a different --state.')
            return info
        time.sleep(0.1)
    raise RuntimeError(f'Host failed to start; inspect {state / "bridge.log"}. Do not delete a live host lock.')


def print_result(result, screen=None):
    if screen:
        images = [item for item in result.get('content', []) if item.get('type') == 'image']
        if not images:
            raise RuntimeError('No image in this result. Poll the completed debug.snapshot operation with --screen.')
        path = Path(screen).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(images[0]['data'], validate=True))
        result = dict(result, savedScreen=str(path))
    # Image data is available through --screen; do not fill the terminal with base64.
    if 'content' in result:
        result = {key: value for key, value in result.items() if key != 'content'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('isError') else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', help='Complete offline package, or FXSTUDIO_PACKAGE')
    parser.add_argument('--state', type=Path, default=Path.cwd() / '.fxstudio/skill/default')
    parser.add_argument('--idle-seconds', type=int, default=7200)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('doctor', 'start', 'status', 'stop', '_serve'):
        sub.add_parser(action)
    discovery = sub.add_parser('discover')
    discovery.add_argument('command', nargs='?')
    call = sub.add_parser('call')
    call.add_argument('command')
    args_group = call.add_mutually_exclusive_group()
    args_group.add_argument('--args-file', type=Path)
    args_group.add_argument('--args-json', default='{}')
    call.add_argument('--request-key')
    call.add_argument('--version', type=int, default=1)
    call.add_argument('--wait-ms', type=int, default=1000)
    call.add_argument('--screen')
    operation = sub.add_parser('operation')
    operation.add_argument('operation_id')
    operation.add_argument('--cancel', action='store_true')
    operation.add_argument('--wait-ms', type=int, default=1000)
    operation.add_argument('--screen')
    events = sub.add_parser('events')
    events.add_argument('--after', type=int, default=0)
    events.add_argument('--limit', type=int, default=100)
    events.add_argument('--session')
    args = parser.parse_args()
    state = args.state.resolve()
    if args.idle_seconds < 30:
        parser.error('--idle-seconds must be at least 30')
    if args.action == '_serve':
        serve(state, package_path(args.package), args.idle_seconds)
        return 0
    if args.action == 'doctor':
        package = package_path(args.package)
        return print_result(dict(package=str(package), windows=os.name == 'nt',
                                 python=str(package / REQUIRED[2]), filesChecked=list(REQUIRED),
                                 state=str(state), helperVersion=1,
                                 note='Presence check only; Verify-Package.ps1 verifies hashes and desktop runtime.'))
    if args.action in ('status', 'stop', 'operation', 'events'):
        info = alive(state)
        if not info:
            if args.action in ('status', 'stop'):
                return print_result(dict(running=False, state=str(state)))
            raise RuntimeError('Host is not running; operation IDs/history cannot survive host restart.')
    else:
        info = ensure_host(state, args.package, args.idle_seconds)
    if args.action in ('start', 'status', 'stop'):
        result = request(info, {'action': 'stop' if args.action == 'stop' else 'status'})
        if args.action == 'stop':
            deadline = time.monotonic() + 40
            pending = True
            while time.monotonic() < deadline:
                try:
                    pending = descriptor(state).get('hostId') == info['hostId']
                except FileNotFoundError:
                    pending = False
                if not pending:
                    break
                time.sleep(0.1)
            if pending:
                raise RuntimeError('Shutdown is still pending; inspect bridge.log before retrying.')
            result['stopped'] = True
        return print_result(result)
    if args.action == 'discover':
        tool, arguments = 'fxstudio_discover', {'command': args.command} if args.command else {}
    elif args.action == 'call':
        arguments = load_json(args.args_file) if args.args_file else json.loads(args.args_json)
        key = args.request_key or uuid.uuid4().hex
        print('requestKey=' + key, file=sys.stderr, flush=True)
        tool, arguments = 'fxstudio_execute', dict(command=args.command, version=args.version,
            arguments=arguments, requestKey=key, waitMs=args.wait_ms)
    elif args.action == 'operation':
        tool, arguments = 'fxstudio_operation', dict(operationId=args.operation_id,
            action='cancel' if args.cancel else 'get', waitMs=args.wait_ms)
    else:
        tool, arguments = 'fxstudio_events', dict(after=args.after, limit=args.limit)
        if args.session:
            arguments['sessionId'] = args.session
    result = request(info, {'action': 'tool', 'name': tool, 'arguments': arguments})
    return print_result(result, getattr(args, 'screen', None))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    sys.stderr.reconfigure(encoding='utf8')
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
