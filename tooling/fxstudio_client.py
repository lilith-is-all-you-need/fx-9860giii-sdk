"""Dependency-free client for FxStudio's MCP stdio transport.

This is an example adapter, not a second automation protocol. All domain command
names and schemas come from fxstudio_discover. Use the same server in MCP clients.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid


class FxStudioClient:
    def __init__(self, executable, package=None):
        command = [str(executable), '--stdio']
        if package:
            command += ['--package', str(package)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.messages = queue.Queue()
        self.stderr = []
        self.counter = 0
        self.lock = threading.RLock()
        def read():
            try:
                for line in self.process.stdout:
                    self.messages.put(json.loads(line))
            except Exception as error:
                self.messages.put(error)
            finally:
                self.messages.put(EOFError('FxStudio agent exited'))
        def errors():
            for line in self.process.stderr:
                self.stderr.append(line.rstrip())
                if len(self.stderr) > 200:
                    del self.stderr[0]
        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()
        try:
            self.rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                   'clientInfo': {'name': 'fxstudio-python-client', 'version': '1.0'}})
            self.notify('notifications/initialized')
        except Exception:
            self.close()
            raise

    def notify(self, method, params=None):
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params or {}}) + '\n')
        self.process.stdin.flush()

    def rpc(self, method, params=None, timeout=15):
        with self.lock:
            self.counter += 1
            request_id = self.counter
            self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                                'method': method, 'params': params or {}}) + '\n')
            self.process.stdin.flush()
            end = time.monotonic() + timeout
            while True:
                response = self.messages.get(timeout=max(0.01, end - time.monotonic()))
                if isinstance(response, Exception):
                    raise response
                if 'id' not in response:
                    continue
                if response['id'] != request_id:
                    raise RuntimeError('Unexpected response id; this example client serializes RPC calls')
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response['result']

    def tool(self, name, arguments=None):
        return self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})

    def execute(self, command, arguments=None, *, timeout=180, request_key=None):
        reply = self.tool('fxstudio_execute', {'command': command, 'version': 1,
                          'arguments': arguments or {}, 'requestKey': request_key or uuid.uuid4().hex, 'waitMs': 1000})
        end = time.monotonic() + timeout
        while True:
            result = reply['structuredContent']
            if 'operation' not in result:
                raise RuntimeError(result.get('error', result))
            operation = result['operation']
            if operation['status'] in ('succeeded', 'failed', 'cancelled'):
                if operation['status'] != 'succeeded':
                    raise RuntimeError(operation.get('error'))
                return reply
            if time.monotonic() >= end:
                self.tool('fxstudio_operation', {'operationId': operation['operationId'], 'action': 'cancel'})
                raise TimeoutError(f'Cancelled timed-out operation {operation["operationId"]}')
            reply = self.tool('fxstudio_operation', {'operationId': operation['operationId'], 'waitMs': 1000})

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', type=Path, required=True)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--screen', type=Path, help='Save the stopped main() framebuffer as PNG')
    args = parser.parse_args()
    with FxStudioClient(args.agent, args.package) as client:
        if not args.project:
            print(json.dumps(client.tool('fxstudio_discover')['structuredContent'], indent=2))
            return
        opened = client.execute('session.open', {'projectPath': str(args.project.resolve())})
        session = opened['structuredContent']['operation']['result']['sessionId']
        try:
            client.execute('build.run', {'sessionId': session, 'configuration': 'Debug'})
            client.execute('debug.launch', {'sessionId': session, 'stopAt': 'main'})
            snapshot = client.execute('debug.snapshot', {'sessionId': session})
            print(json.dumps(snapshot['structuredContent'], indent=2))
            if args.screen:
                import base64
                image = next(block for block in snapshot['content'] if block['type'] == 'image')
                args.screen.write_bytes(base64.b64decode(image['data']))
        finally:
            client.execute('session.close', {'sessionId': session})


if __name__ == '__main__':
    main()
