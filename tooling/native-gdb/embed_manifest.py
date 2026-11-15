"""Embed a UTF-8 Windows activation manifest in our unsigned GDB executable."""
import ctypes
from ctypes import wintypes
from pathlib import Path

def embed(executable,manifest):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LoadLibraryExW.argtypes=[wintypes.LPCWSTR,wintypes.HANDLE,wintypes.DWORD]
    kernel.LoadLibraryExW.restype=wintypes.HMODULE
    kernel.FreeLibrary.argtypes=[wintypes.HMODULE]
    CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_ssize_t)
    kernel.EnumResourceLanguagesW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,CALLBACK,ctypes.c_ssize_t]
    languages=[]
    @CALLBACK
    def found(module,kind,name,language,parameter):
        languages.append(language);return True
    module=kernel.LoadLibraryExW(str(executable),None,2)
    if not module:raise ctypes.WinError(ctypes.get_last_error())
    try:kernel.EnumResourceLanguagesW(module,24,1,found,0)
    finally:kernel.FreeLibrary(module)
    kernel.BeginUpdateResourceW.argtypes=[wintypes.LPCWSTR,wintypes.BOOL]
    kernel.BeginUpdateResourceW.restype=wintypes.HANDLE
    kernel.UpdateResourceW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD]
    kernel.EndUpdateResourceW.argtypes=[wintypes.HANDLE,wintypes.BOOL]
    handle=kernel.BeginUpdateResourceW(str(executable),False)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    payload=Path(manifest).read_bytes();buffer=ctypes.create_string_buffer(payload)
    try:
        for language in languages or [0]:
            if not kernel.UpdateResourceW(handle,24,1,language,buffer,len(payload)):
                raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        kernel.EndUpdateResourceW(handle,True)
        raise
    if not kernel.EndUpdateResourceW(handle,False):raise ctypes.WinError(ctypes.get_last_error())
