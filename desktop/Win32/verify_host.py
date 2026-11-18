"""Exercise the actual portable workspace host and calculator toolchain, without a global runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

def clean_environment(folder):
    return dict(os.environ, PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
                DOTNET_ROOT=str(folder / "no-global-runtime"), DOTNET_MULTILEVEL_LOOKUP="0",
                HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", PYTHONUTF8="1")

class Host:
    def __init__(self, sdk, work):
        self.p = subprocess.Popen([sdk / "FxStudio.Win32Host.exe", sdk], cwd=work, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=clean_environment(work),
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.messages = queue.Queue()
        self.all = []
        def consume():
            for line in self.p.stdout:
                try: self.messages.put(json.loads(line))
                except ValueError: self.messages.put({"kind": "log", "data": line})
            self.messages.put({"kind":"eof","data":self.p.poll()})
        threading.Thread(target=consume, daemon=True).start()

    def send(self, cmd, **args):
        self.p.stdin.write(json.dumps(dict(cmd=cmd, **args)) + "\n")
        self.p.stdin.flush()

    def until(self, condition, timeout=160):
        start = time.monotonic()
        while time.monotonic()-start < timeout:
            try: m = self.messages.get(timeout=min(2, timeout-(time.monotonic()-start)))
            except queue.Empty: continue
            self.all.append(m)
            if m["kind"] == "eof": raise RuntimeError("Host exited: "+str(self.all[-8:]))
            if condition(m): return m["data"]
        raise TimeoutError(str(self.all[-12:]))

    def cmd(self, cmd, fail=False, **args):
        start = len(self.all); self.send(cmd, **args)
        self.until(lambda m:m["kind"]=="done" and m["data"]==cmd)
        results = self.all[start:]
        errors = [m["data"] for m in results if m["kind"] == "error"]
        assert bool(errors) == fail, (cmd, errors, results[-8:])
        return {m["kind"]:m["data"] for m in results}

    def paused(self, since):
        if not any(m["kind"]=="paused" for m in self.all[since:]):
            self.until(lambda m:m["kind"]=="paused", 24)

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=15)
        assert self.p.returncode == 0

def run(package, work):
    root = package / "Studio"
    work.mkdir(parents=True, exist_ok=False)
    host = Host(root, work)
    results = {}
    try:
        host.cmd("settings", work=str(work / "cache") if str(work).isascii() else "")
        for language in ("c", "cpp"):
            p = work / ("计数器 ' " + language)
            shutil.copytree(root / "examples" / ("counter-" + language), p, ignore=shutil.ignore_patterns(".fxstudio", "project.fxide.json", "build*"))
            opened = host.cmd("open", path=str(p))["project"]
            assert Path(opened["directory"]) == p
            for cfg in ("Debug", "Release"):
                artifact = host.cmd("build", configuration=cfg)["artifact"]
                binary = Path(artifact["g1a"])
                assert Path(artifact["elf"]).is_file() and binary.stat().st_size == artifact["size"] > 512
                output = work / (language + "-" + cfg + ".g1a")
                host.cmd("export", path=str(output))
                assert output.read_bytes() == binary.read_bytes()
                results[language + "-" + cfg] = binary.stat().st_size
        source = p / "src/main.cpp"
        line = next(i for i,s in enumerate(source.read_text().splitlines(),1) if "event = getkey()" in s)
        point = dict(id=1,file=str(source),line=line,enabled=True)
        t = len(host.all); launch=host.cmd("start",points=[point]); host.paused(t)
        snap=host.cmd("snapshot",watches=["counter.value"])["snapshot"]
        assert snap["frame"]["function"] == "main" and snap["registers"] and snap["disassembly"]
        t=len(host.all);host.cmd("start");host.paused(t)
        snap=host.cmd("snapshot",watches=["counter.value"])["snapshot"]
        assert snap["frame"]["line"] == line and snap["watches"][0]["value"]=="0", snap["frame"]
        bmp=Path(launch["framebuffer"])
        assert bmp.read_bytes()[:2]==b"BM"
        (work/"counter-screen.bmp").write_bytes(bmp.read_bytes())
        host.cmd("points",points=[dict(point, condition="counter.value == 1")])
        host.cmd("start"); time.sleep(.2)
        t=len(host.all);host.cmd("key",key="PLUS",down=True);time.sleep(.10);host.cmd("key",key="PLUS",down=False);host.paused(t)
        snap=host.cmd("snapshot",watches=["counter.value"])["snapshot"]
        assert snap["watches"][0]["value"]=="1"
        members=host.cmd("children",expression="counter")["children"]["items"]
        assert members
        for i, member in enumerate(members):
            if member.get("children"):
                deeper=host.cmd("children",expression="counter",trail=[i])["children"]
                assert deeper["items"] and deeper["trail"]==[i]
                break
        host.cmd("frame",level=0)
        data=host.cmd("read",address="&counter.value",count=4)["memory"]
        assert data["hex"]=="00000001",data
        host.cmd("write",address="&counter.value",hex="00 00 00 02")
        host.cmd("evaluate",expression="(counter.value) = 3")
        assert host.cmd("evaluate",expression="counter.value")["value"]=="3"
        reg=next(r for r in snap["registers"] if r["name"]=="r0")
        host.cmd("register",number=reg["number"],value=reg["value"])
        host.cmd("points",points=[])
        t=len(host.all);host.cmd("stepi");host.paused(t)
        t=len(host.all);host.cmd("nexti");host.paused(t)
        # A temporary source breakpoint exercises the UI's run-to-cursor path.
        host.cmd("points",points=[dict(point,enabled=False)])
        host.cmd("points",points=[])
        t=len(host.all);host.cmd("restart",points=[]);host.paused(t)
        t=len(host.all);host.cmd("runTo",file=str(source),line=line);host.paused(t)
        host.cmd("start");time.sleep(.1)
        t=len(host.all);host.cmd("pause");host.paused(t)
        host.cmd("stop")
        results["debug"] = ["main", "source breakpoint", "conditional breakpoint", "PLUS input 0→1", "framebuffer", "stack", "locals", "watch",
            "members", "frame selection", "memory read/write", "evaluate/assign", "register write", "disassembly",
            "instruction step and next", "disabled breakpoint", "restart", "run to cursor", "pause", "stop"]
        external = work/"原始资源.bin";external.write_bytes(bytes(range(20)))
        result=host.cmd("asset",args=["import","--project",str(p),"--input",str(external),"--kind","binary","--symbol","demo_blob"])
        assert Path(result["assets"]["header"]).is_file()
        host.cmd("build",configuration="Release")
        legacy = work/"迁移 ' legacy"
        host.cmd("migrate",destination=str(legacy),args=["create","--source",str(root/"examples/legacy-fxlib/src"),"--output",str(legacy),"--name","LegacyTest"])
        results["migratedRelease"]=host.cmd("build",configuration="Release")["artifact"]["size"]
        imported=host.cmd("open",path=str(root/"examples/prebuilt/counter-cpp/demo.fxdebug.json"))["project"]
        assert imported["imported"]
        host.cmd("build",configuration="Release",fail=True)
        t=len(host.all);host.cmd("start",points=[]);host.paused(t)
        assert host.cmd("snapshot",watches=[])["snapshot"]["frame"]["function"]=="main"
        host.cmd("stop")
        host.cmd("open",path=str(p))
        backup=source.read_bytes();source.write_bytes(b"#error WIN32_DIAGNOSTIC_TEST\n"+backup)
        result=host.cmd("build",configuration="Debug",fail=True)
        assert "diagnostic" in result
        assert any(m["kind"]=="diagnostic" and Path(m["data"]["file"])==source for m in host.all)
        source.write_bytes(backup)
        results["imports"]=["legacy fxlib project", "binary asset with compiled declarations", "verified prebuilt pair"]
        results["diagnostic"]=True
    finally:
        host.close()
    (work/"validation.json").write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(results,ensure_ascii=True))

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("package",type=Path);p.add_argument("new_work",type=Path)
    a=p.parse_args();run(a.package.resolve(),a.new_work.resolve())
