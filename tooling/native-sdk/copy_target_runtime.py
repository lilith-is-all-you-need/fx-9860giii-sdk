"""Copy only target headers, archives and objects from the fixed SDK snapshot.

This never copies Linux host executables or modifies the snapshot.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import ctypes
from ctypes import wintypes

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ['USERPROFILE']) / '.codex-build-envs/native-sdk-20261114'
SOURCE = Path(os.environ['USERPROFILE']) / '.codex-build-envs/fxsdk-dev-20261114/rootfs/root/.local/share/fxsdk/sysroot'
PREFIX = WORK / 'prefix'
records = []
def readable_source(path):
    info = path.lstat()
    if not getattr(info, 'st_file_attributes', 0) & 0x400:
        return path
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0, 7, None, 3, 0x00200000 | 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(16384)
    received = wintypes.DWORD()
    try:
        if not kernel.DeviceIoControl(handle, 0x000900a8, None, 0, buffer, len(buffer), ctypes.byref(received), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    raw = buffer.raw[:received.value]
    if int.from_bytes(raw[:4], 'little') != 0xa000001d:
        raise RuntimeError(f'Unexpected reparse tag: {path}')
    destination = raw[12:].decode('utf-8')
    if destination.startswith('/'):
        linux_prefix = '/root/.local/share/fxsdk/sysroot/'
        if not destination.startswith(linux_prefix):
            raise RuntimeError(f'Target link escapes SDK: {path} -> {destination}')
        result = SOURCE / destination[len(linux_prefix):]
    else:
        result = path.parent / destination
    if not Path(os.path.abspath(result)).is_relative_to(SOURCE):
        raise RuntimeError(f'Target link escapes SDK: {path}')
    return readable_source(result)

for subtree in ('sh3eb-elf/include', 'sh3eb-elf/lib', 'lib/gcc/sh3eb-elf/14.1.0'):
    for source in (SOURCE / subtree).rglob('*'):
        actual = readable_source(source)
        if not actual.is_file():
            continue
        relative = source.relative_to(SOURCE)
        if subtree.startswith('lib/gcc') and source.suffix not in ('.a', '.o'):
            continue
        if source.suffix == '.la':
            continue  # Libtool archives embed the old Linux installation path.
        target = PREFIX / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual, target)
        records.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
document = {'source': str(SOURCE), 'compilerVersion': '14.1.0', 'target': 'sh3eb-elf', 'files': records}
(HERE / 'target-runtime-manifest.json').write_text(json.dumps(document, indent=2), encoding='utf-8')
print(f'Copied {len(records)} target files, {sum(x["bytes"] for x in records):,} bytes')
