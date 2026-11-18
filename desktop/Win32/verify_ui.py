"""Windows desktop acceptance checks against a private SDK workspace and the real HWND controls."""
import argparse
import ctypes as c
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from verify_host import clean_environment

u, g = c.windll.user32, c.windll.gdi32
P = c.c_void_p
L = c.c_ssize_t
CALLBACK = c.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
def function(dll, name, result, args):
    f = getattr(dll, name); f.restype = result; f.argtypes = args; return f

message = function(u, "SendMessageW", L, [P, wt.UINT, c.c_size_t, L])
post = function(u, "PostMessageW", wt.BOOL, [P, wt.UINT, c.c_size_t, L])
control = function(u, "GetDlgItem", P, [P, c.c_int])
child = function(u, "FindWindowExW", P, [P, P, wt.LPCWSTR, wt.LPCWSTR])
enabled = function(u, "IsWindowEnabled", wt.BOOL, [P])
wm_text, wm_command = 0x000D, 0x0111
def text(h):
    buf=c.create_unicode_buffer(message(h, 0x000E, 0, 0)+1)
    message(h, wm_text, len(buf), c.addressof(buf)); return buf.value

def wait(fn, label, timeout=35):
    until = time.monotonic()+timeout
    while time.monotonic()<until:
        result=fn()
        if result: return result
        time.sleep(.07)
    raise RuntimeError("Timeout: " + label)

def windows(pid):
    result=[]
    @CALLBACK
    def visit(h, _):
        owner=wt.DWORD(); u.GetWindowThreadProcessId(h,c.byref(owner))
        if owner.value==pid: result.append(h)
        return True
    u.EnumWindows(visit,0);return result

def classname(h):
    s=c.create_unicode_buffer(256);u.GetClassNameW(h,s,256);return s.value

def capture(h, path):
    r=wt.RECT();u.GetWindowRect(h,c.byref(r));w=r.right-r.left;hh=r.bottom-r.top
    dc=function(u,"GetWindowDC",P,[P])(h)
    mem=function(g,"CreateCompatibleDC",P,[P])(dc)
    bmp=function(g,"CreateCompatibleBitmap",P,[P,c.c_int,c.c_int])(dc,w,hh)
    select=function(g,"SelectObject",P,[P,P]);prev=select(mem,bmp)
    try:
        assert function(u,"PrintWindow",wt.BOOL,[P,P,wt.UINT])(h,mem,2)
        select(mem,prev)
        info=struct.pack("<IiiHHIIiiII",40,w,hh,1,32,0,w*hh*4,0,0,0,0)
        header=c.create_string_buffer(info);buf=c.create_string_buffer(w*hh*4)
        got=function(g,"GetDIBits",c.c_int,[P,P,wt.UINT,wt.UINT,P,P,wt.UINT])(mem,bmp,0,hh,buf,header,0)
        assert got==hh
        path.write_bytes(struct.pack("<2sIHHI",b"BM",54+len(buf),0,0,54)+info+buf.raw)
    finally:
        function(g,"DeleteObject",wt.BOOL,[P])(bmp);function(g,"DeleteDC",wt.BOOL,[P])(mem);function(u,"ReleaseDC",c.c_int,[P,P])(h,dc)

def run(package, work):
    work.mkdir(parents=True,exist_ok=False)
    project=work/"GUI 中文's C++"
    shutil.copytree(package/"Studio/examples/counter-cpp",project,ignore=shutil.ignore_patterns(".fxstudio","project.fxide.json","build*"))
    project_label="Counter · C++"
    (project/"project.fxide.json").write_text(json.dumps({"schemaVersion":1,"name":project_label,"sourceDirectory":".","buildDirectory":".fxstudio/build"}),encoding="utf-8")
    source=project/"src/main.cpp"
    rows=source.read_text().splitlines()
    loop=next(i for i,s in enumerate(rows) if "event = getkey()" in s)
    u.SetProcessDpiAwarenessContext(P(-4))
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    process=subprocess.Popen([package/"FxStudio.Win32.exe","--settings-dir",str(work/"settings"),"--project",str(project),"--language","zh-CN"],
        cwd=work,startupinfo=startup,env=clean_environment(work))
    checks=[]
    h=None
    def find_window(cls):
        return next((w for w in windows(process.pid) if classname(w)==cls),None)
    def command(id):
        assert post(h,wm_command,id,0)
    def field_value(hwnd, value):
        data=c.create_unicode_buffer(str(value))
        message(hwnd,0x000C,0,c.addressof(data))
    def dialog(title):
        return wait(lambda:next((w for w in windows(process.pid) if classname(w)=="#32770" and text(w)==title), None),title)
    def submit_file(title, path):
        box=dialog(title)
        def filename_field():
            edits=[]
            @CALLBACK
            def visit(hwnd, _):
                if classname(hwnd)=="Edit": edits.append(hwnd)
                return True
            u.EnumChildWindows(box,visit,0)
            for field in edits:
                if u.GetDlgCtrlID(field) in (1001,1148,0x480) and u.IsWindowVisible(field):
                    return field
            return None
        field=wait(filename_field,"file name edit")
        time.sleep(.3)
        field_value(field,path)
        assert text(field)==str(path)
        time.sleep(.12)
        ok=control(box,1)
        if ok: post(ok,0x00f5,0,0)
        else: post(box,wm_command,1,0)
    try:
        h=wait(lambda:find_window("FxStudio.NativeWorkspace"),"native main window")
        wait(lambda:project_label in text(h),"project opened")
        dpi=u.GetDpiForWindow(h)
        # Target only the spawned process. SWP_NOACTIVATE keeps the user's focus.
        u.SetWindowPos(h,0,80,65,round(1260*dpi/96),round(795*dpi/96),0x14)
        u.ShowWindow(h,4)
        ed=wait(lambda:child(h,None,"Scintilla",None),"Scintilla editor")
        assert message(ed,2006,0,0)>500
        assert classname(control(h,231))=="SysTreeView32"
        assert message(control(h,233),0x1304,0,0)==9
        checks+=["C++ project / Unicode path", "native editor / project tree / nine inspector tabs"]
        # Save a real source edit and undo it again.
        original=source.read_bytes();message(ed,2025,0,0)
        message(ed,0x0102,ord(" "),0);command(104)
        wait(lambda:source.read_bytes()!=original,"source save")
        message(ed,2176,0,0);command(104);wait(lambda:source.read_bytes()==original,"source undo/save")
        checks+=["edit / save / undo"]
        message(ed,2024,loop,0);command(142)
        wait(lambda:(project/".fxstudio/session.json").is_file(),"breakpoint persistence")
        session=lambda:json.loads((project/".fxstudio/session.json").read_text(encoding="utf-8-sig"))
        wait(lambda:any(b["Line"]==loop+1 for b in session()["Breakpoints"]),"source breakpoint stored")
        command(132)
        start=control(h,132);out=control(h,234)
        wait(lambda:"继续" in text(start) and enabled(start),"debugger stopped at main",100)
        time.sleep(.45);wait(lambda:enabled(start),"main snapshot")
        command(132)
        wait(lambda:"继续" in text(start) and enabled(start) and message(ed,2166,message(ed,2008,0,0),0)==loop,"draw breakpoint",32)
        wait(lambda:enabled(control(h,170)),"live framebuffer")
        command(178)
        box=dialog("添加监视")
        field_value(control(box,100),"counter.value");post(box,wm_command,1,0)
        wait(lambda:message(control(h,235),0x1004,0,0)==1 and enabled(start),"watch counter.value")
        # Send one physical key hold/release through the native keypad button.
        command(132);wait(lambda:text(start)=="调试" and enabled(control(h,133)),"target running")
        plus=control(h,326);message(plus,0x0201,1,0x00090009);time.sleep(.12);message(plus,0x0202,0,0x00090009)
        wait(lambda:"继续" in text(start) and enabled(start),"key hit source breakpoint")
        time.sleep(.3);capture(h,work/"workspace.bmp")
        command(170);screen=work/"screen.png";submit_file("保存原始屏幕",screen)
        wait(lambda:screen.is_file(),"PNG export")
        assert screen.read_bytes()[:8]==b"\x89PNG\r\n\x1a\n" and struct.unpack(">II",screen.read_bytes()[16:24])==(128,64)
        command(169);zoom=wait(lambda:find_window("FxStudio.NativeInspector"),"live screen window");post(zoom,0x10,0,0)
        checks+=["native F5 command / real build / breakpoint / live screen / zoom", "watch dialog / keypad PLUS / native PNG export"]
        wait(lambda:enabled(start),"debug snapshot complete");command(134)
        wait(lambda:enabled(control(h,130)),"stop debugger")
        message(control(h,230),0x14e,1,0);command(130)
        outdir=project/".fxstudio/build/Release"
        wait(lambda: list(outdir.rglob("*.g1a")) and enabled(control(h,130)),"Release G1A",90)
        checks+=["Release build"]
        asset=work/"资源.bin";asset.write_bytes(b"Win32 asset")
        command(160);submit_file("选择要导入的资源",asset)
        box=dialog("导入工程资源");message(control(box,100),0x014e,2,0)
        field_value(control(box,101),"native_blob");post(box,wm_command,1,0)
        wait(lambda:any("native_blob" in p.read_text(encoding="utf-8") for p in project.rglob("project_assets.h")),"native asset import")
        wait(lambda:enabled(control(h,130)),"asset transaction complete")
        checks+=["asset picker / binary resource dialog / C declaration"]
        command(167);ref=wait(lambda:find_window("FxStudio.NativeInspector"),"knowledge window")
        query=child(ref,None,"Edit",None)
        s=c.create_unicode_buffer("0x042C");message(query,0x000C,0,c.addressof(s))
        choices=child(ref,None,"ListBox",None);assert 0<message(choices,0x018B,0,0)<50
        post(ref,0x10,0,0);checks+=["live knowledge search"]
        command(165);wait(lambda:text(control(h,130))=="Build","English toggle")
        command(164);wait(lambda:text(control(h,130))=="构建","Chinese toggle")
        checks+=["Chinese / English"]
        post(h,0x10,0,0);assert process.wait(timeout=15)==0
        print(json.dumps(checks));(work/"validation.json").write_text(json.dumps(checks,indent=2),encoding="utf-8")
    except BaseException:
        if h:
            print("Workspace:",text(h),"Outputs:",text(control(h,234))[-3500:],flush=True)
            capture(h,work/"failure.bmp")
        raise
    finally:
        if process.poll() is None:
            if h: post(h,0x10,0,0)
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("package",type=Path);parser.add_argument("new_work",type=Path)
    args=parser.parse_args();run(args.package.resolve(),args.new_work.resolve())
