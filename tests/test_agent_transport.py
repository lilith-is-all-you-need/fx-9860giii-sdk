"""Exercise the published FxStudio MCP transport without launching a calculator.

Uses only Python's standard library. Each case starts its own host process; all
sessions are metadata-only, and the input project is never edited or built.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def spawn(agent, package):
    return subprocess.Popen(
        [str(agent), '--stdio', '--package', str(package)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=0, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def encoded(message, ensure_ascii=True):
    return (json.dumps(message, ensure_ascii=ensure_ascii, separators=(',', ':')) + '\n').encode('utf-8')


def write_all(stream, data):
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if not written:
            raise BrokenPipeError('Agent input was closed')
        view = view[written:]
    stream.flush()


def initialize_message():
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-11-25', 'capabilities': {},
        'clientInfo': {'name': 'fxstudio-transport-regression', 'version': '1.0'}}}


class Client:
    def __init__(self, agent, package):
        self.process = spawn(agent, package)
        self.messages = queue.Queue()
        self.pending = {}
        self.next_id = 1
        self.stderr = []

        def read_output():
            try:
                for line in self.process.stdout:
                    self.messages.put(json.loads(line))
            except Exception as error:
                self.messages.put(error)
            finally:
                self.messages.put(EOFError('Agent exited: ' + ' | '.join(self.stderr[-5:])))

        def read_errors():
            for line in self.process.stderr:
                self.stderr.append(line.decode('utf-8', errors='replace').rstrip())
                if len(self.stderr) > 100:
                    del self.stderr[0]

        self.threads = [threading.Thread(target=read_output, daemon=True),
                        threading.Thread(target=read_errors, daemon=True)]
        for thread in self.threads:
            thread.start()
        try:
            write_all(self.process.stdin, encoded(initialize_message()))
            result = self.receive(1)
            require('result' in result, 'initialize failed: ' + repr(result))
            self.notify('notifications/initialized')
        except Exception:
            self.close()
            raise

    def notify(self, method, params=None):
        write_all(self.process.stdin, encoded({'jsonrpc': '2.0', 'method': method, 'params': params or {}}))

    def request(self, method, params=None, *, ensure_ascii=True):
        self.next_id += 1
        request_id = self.next_id
        write_all(self.process.stdin, encoded({'jsonrpc': '2.0', 'id': request_id,
                  'method': method, 'params': params or {}}, ensure_ascii=ensure_ascii))
        return request_id

    def receive(self, request_id, timeout=15):
        if request_id in self.pending:
            return self.pending.pop(request_id)
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty as error:
                raise TimeoutError(f'No response for RPC {request_id}') from error
            if isinstance(reply, Exception):
                raise reply
            if 'id' not in reply:
                continue
            if reply['id'] == request_id:
                return reply
            self.pending[reply['id']] = reply

    def rpc(self, method, params=None, *, ensure_ascii=True):
        response = self.receive(self.request(method, params, ensure_ascii=ensure_ascii))
        require('error' not in response, 'Unexpected RPC error: ' + repr(response))
        return response['result']

    def tool(self, name, args=None, *, ensure_ascii=True):
        return self.rpc('tools/call', {'name': name, 'arguments': args or {}}, ensure_ascii=ensure_ascii)

    def submit(self, command, args, key, wait=0, *, ensure_ascii=True):
        return self.tool('fxstudio_execute', {'command': command, 'version': 1,
                         'arguments': args, 'requestKey': key, 'waitMs': wait}, ensure_ascii=ensure_ascii)

    def completed(self, reply):
        deadline = time.monotonic() + 15
        while True:
            data = reply['structuredContent']
            require('operation' in data, 'Submission rejected: ' + repr(data))
            operation = data['operation']
            if operation['status'] in ('succeeded', 'failed', 'cancelled'):
                return operation
            require(time.monotonic() < deadline, 'Operation did not complete')
            reply = self.tool('fxstudio_operation', {'operationId': operation['operationId'], 'waitMs': 1000})

    def close(self):
        try:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            if self.process.poll() is None:
                self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def error_code(reply):
    return reply.get('structuredContent', {}).get('error', {}).get('code')


def unicode_and_argument_types(agent, package, project):
    with Client(agent, package) as client:
        arguments = {'projectPath': str(project)}
        key = 'transport-中文-retry'
        first = client.completed(client.submit('session.open', arguments, key, 1000, ensure_ascii=False))
        require(first['status'] == 'succeeded', repr(first))
        second = client.completed(client.submit('session.open', arguments, key, 1000, ensure_ascii=True))
        require(first['operationId'] == second['operationId'], 'Equivalent escaped Unicode submitted a second operation')
        require(first['result']['sessionId'] == second['result']['sessionId'], 'Equivalent retry opened another session')
        require(first['version'] == second['version'] == 1, 'Operation lost command version')
        session = first['result']['sessionId']
        changed = client.submit('session.open', {'projectPath': str(project), 'sdkPath': str(package / 'sdk/native')}, key)
        require(error_code(changed) == 'REQUEST_KEY_CONFLICT', 'Different input was not rejected')
        invalid = client.tool('fxstudio_operation', {'operationId': first['operationId'], 'action': False})
        require(invalid.get('isError') is True and error_code(invalid) == 'INVALID_ARGUMENT', 'Boolean action silently defaulted to get')
        invalid_wait = client.tool('fxstudio_operation', {'operationId': first['operationId'], 'waitMs': '0'})
        require(error_code(invalid_wait) == 'INVALID_ARGUMENT', 'String waitMs was accepted')
        wrong_version = client.tool('fxstudio_execute', {'command': 'session.list', 'version': 99, 'arguments': {}, 'requestKey': 'bad-version'})
        require(error_code(wrong_version) == 'UNSUPPORTED_VERSION', 'Unsupported command version was accepted')
        sessions = client.completed(client.submit('session.list', {}, 'list-once', 1000))['result']['sessions']
        require(len(sessions) == 1, 'Idempotent retry duplicated session')
        closed = client.completed(client.submit('session.close', {'sessionId': session}, 'close-once', 1000))
        require(closed['status'] == 'succeeded' and closed['result']['closed'], 'Session close failed')
        return {'equivalentUnicodeRetry': True, 'conflictingRetryRejected': True,
                'wrongArgumentTypesRejected': True, 'versionReportedAndRejected': True}


def cancellation_race(agent, package, project):
    with Client(agent, package) as client:
        successes = cancelled = 0
        total = 1024
        for offset in range(0, total, 16):
            ids = []
            for item in range(16):
                request = client.request('tools/call', {'name': 'fxstudio_discover', 'arguments': {'command': 'session.list'}})
                client.notify('notifications/cancelled', {'requestId': request, 'reason': 'transport race regression'})
                ids.append(request)
            for request in ids:
                reply = client.receive(request)
                if 'error' in reply:
                    require(reply['error']['code'] == -32800, 'Unexpected cancellation response: ' + repr(reply))
                    cancelled += 1
                else:
                    successes += 1
                # Late/repeated cancellation must also be harmless after CTS disposal.
                client.notify('notifications/cancelled', {'requestId': request})
            require(client.process.poll() is None, f'Host exited during cancellation batch {offset}')
        require(client.rpc('ping') == {}, 'Host no longer serves requests after cancellation race')
        return {'requests': total, 'completedResponses': successes, 'cancelledResponses': cancelled,
                'lateRepeatedCancellations': total, 'finalPing': True}


def oversized_unterminated_input(agent, package, project):
    process = spawn(agent, package)
    errors = []
    started = time.monotonic()

    def write_oversized():
        try:
            # Keep stdin open and intentionally omit a newline; rejection must precede EOF.
            write_all(process.stdin, b'x' * (1_048_576 + 8192))
        except (BrokenPipeError, OSError) as error:
            errors.append(type(error).__name__)

    writer = threading.Thread(target=write_oversized, daemon=True)
    writer.start()
    try:
        code = process.wait(timeout=8)
        elapsed = time.monotonic() - started
        require(not process.stdin.closed, 'Test incorrectly supplied EOF before rejection')
        stderr = process.stderr.read().decode('utf-8', errors='replace')
        require(code != 0 and 'framing exceeds' in stderr, 'Missing oversized framing failure: ' + stderr)
        return {'bytesSentAttempted': 1_048_576 + 8192, 'newlineSent': False,
                'stdinOpenAtExit': True, 'exitCode': code, 'exitSeconds': round(elapsed, 3), 'stderr': stderr.strip()}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        writer.join(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def unread_stdout_eof(agent, package, project):
    process = spawn(agent, package)
    handshake = queue.Queue()

    def read_once():
        try:
            handshake.put(json.loads(process.stdout.readline()))
        except Exception as error:
            handshake.put(error)

    try:
        thread = threading.Thread(target=read_once, daemon=True)
        thread.start()
        write_all(process.stdin, encoded(initialize_message()))
        reply = handshake.get(timeout=10)
        require(isinstance(reply, dict) and 'result' in reply, 'Initialize failed')
        thread.join(timeout=1)
        require(not thread.is_alive(), 'Handshake reader did not finish')
        # Full catalogs are much larger than the pipe capacity; after the handshake
        # absolutely no reader consumes stdout until the process has exited.
        payload = encoded({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        for request_id in range(2, 26):
            payload += encoded({'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                                'params': {'name': 'fxstudio_discover', 'arguments': {}}})
        write_all(process.stdin, payload)
        time.sleep(0.15)
        started = time.monotonic()
        process.stdin.close()
        code = process.wait(timeout=8)
        elapsed = time.monotonic() - started
        require(code == 0, f'EOF with unread stdout exited with {code}')
        return {'catalogResponsesRequested': 24, 'stdoutReadAfterInitialize': False,
                'exitCode': code, 'exitAfterEofSeconds': round(elapsed, 3)}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def quota_and_reserved_close(agent, package, project):
    with Client(agent, package) as client:
        limits = client.tool('fxstudio_discover')['structuredContent']['limits']
        capacity = limits['maximumOperations']
        reserve = limits['reservedCloseOperations']
        require(capacity == 1024 and reserve >= 8, 'Unexpected operation budget')
        sessions = []
        first = None
        for index in range(8):
            reply = client.submit('session.open', {'projectPath': str(project)}, f'open-{index}', 1000)
            op = client.completed(reply)
            require(op['status'] == 'succeeded', 'Open failed: ' + repr(op))
            sessions.append(op['result']['sessionId'])
            if first is None:
                first = op
        for index in range(capacity - 8):
            reply = client.submit('session.list', {}, f'fill-{index}')
            require('operation' in reply['structuredContent'], f'Budget rejected early at {index + 8}')
        client.completed(reply)
        rejected = client.submit('session.list', {}, 'beyond-budget')
        require(error_code(rejected) == 'OPERATION_LIMIT', 'Normal operation exceeded budget')
        retried = client.completed(client.submit('session.open', {'projectPath': str(project)}, 'open-0'))
        require(retried['operationId'] == first['operationId'], 'Retry stopped working at capacity')
        before = client.tool('fxstudio_events', {'after': 0, 'limit': 1})['structuredContent']['latestCursor']
        for index, session in enumerate(sessions):
            operation = client.completed(client.submit('session.close', {'sessionId': session}, f'close-{index}', 1000))
            require(operation['status'] == 'succeeded' and operation['result']['closed'], 'Reserved close failed: ' + repr(operation))
        events = client.tool('fxstudio_events', {'after': before, 'limit': 200})['structuredContent']['events']
        closed_ids = {e['sessionId'] for e in events if e['kind'] == 'session.closed'}
        require(closed_ids == set(sessions), 'Not all sessions emitted close events')
        exhausted = client.submit('session.close', {'sessionId': sessions[0]}, 'close-beyond-reserve')
        require(error_code(exhausted) == 'OPERATION_LIMIT', 'Reserved budget is unbounded')
        return {'normalOperations': capacity, 'normalLimitEnforced': True,
                'retryAtCapacity': True, 'reservedSuccessfulSessionCloses': len(closed_ids),
                'reservedLimitEnforced': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', type=Path, required=True)
    parser.add_argument('--package', type=Path, default=ROOT / 'dist-windows/FxStudio-0.1.1-win-x64')
    parser.add_argument('--project', type=Path, default=ROOT / 'examples/counter-cpp')
    parser.add_argument('--output', type=Path, default=ROOT / 'research/agent-transport-validation.json')
    args = parser.parse_args()
    agent, package, project = args.agent.resolve(), args.package.resolve(), args.project.resolve()
    records = []
    cases = [unicode_and_argument_types, cancellation_race, oversized_unterminated_input,
             unread_stdout_eof, quota_and_reserved_close]
    for test in cases:
        started = time.monotonic()
        try:
            details = test(agent, package, project)
            record = {'name': test.__name__, 'passed': True, 'details': details}
        except Exception as error:
            record = {'name': test.__name__, 'passed': False, 'error': f'{type(error).__name__}: {error}'}
        record['seconds'] = round(time.monotonic() - started, 3)
        records.append(record)
        print(('PASS' if record['passed'] else 'FAIL') + ' ' + test.__name__ + f" ({record['seconds']}s)", flush=True)
        if not record['passed']:
            print(record['error'], flush=True)
    hashes = {}
    for name in ('FxStudio.Agent.exe', 'FxStudio.Agent.dll', 'FxStudio.Automation.dll', 'FxStudio.Core.dll'):
        path = agent.parent / name
        if path.exists():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {'passed': all(item['passed'] for item in records),
              'timestampUtc': datetime.now(timezone.utc).isoformat(),
              'agent': str(agent), 'package': str(package), 'project': str(project),
              'scope': 'Published MCP transport boundaries; no calculator process launched; input project unmodified.',
              'binarySha256': hashes, 'checks': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
