#!/usr/bin/env python3
"""Cancel only the recorded live build session for an exact build directory."""
import json
import os
from pathlib import Path
import signal
import sys

def start_time(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]

def main():
    if len(sys.argv)!=2: raise SystemExit('Usage: cancel-build BUILD_DIRECTORY')
    directory=Path(sys.argv[1]).resolve()
    record=directory/'.fxide-build.pid'
    if not record.exists(): return
    data=json.loads(record.read_text())
    pid=int(data['pid'])
    try:
        command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if (start_time(pid)!=data['startTime'] or os.getpgid(pid)!=pid
            or data['buildDirectory']!=str(directory)
            or not any(x.endswith(b'/build-project') for x in command)):
            raise SystemExit('Refusing to cancel: process identity does not match')
        os.killpg(pid,signal.SIGTERM)
        print('Build cancellation requested')
    except ProcessLookupError: pass
    except FileNotFoundError: pass

if __name__=='__main__': main()
