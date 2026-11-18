"""Assemble an independent Win32 SDK from a manifest-verified full Loader Suite."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tooling"))
from package_components import copy_development_runtime, copy_loader_runtime, digest, source_file
from check_emulator_build import BRIDGE_SOURCES, UPSTREAM, copy_verified_emulator
from editor_deps import INPUTS, prepare

def records(folder):
    return sorted(p for p in folder.rglob("*") if p.is_file())

def update_native_service(target):
    sdk = target / "sdk/native"
    path = sdk / "manifest.json"
    inventory = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = {row["path"]: row for row in inventory["files"]}
    for name in ("build-native.py", "build-project.py", "compiler-launcher.py"):
        rel = "service/" + name
        output = sdk / rel
        shutil.copy2(ROOT / "tooling" / name, output)
        entries[rel].update(bytes=output.stat().st_size, sha256=digest(output))
    inventory["totalBytes"] = sum(row["bytes"] for row in entries.values())
    path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")

def assemble_base(base, dest):
    if dest.exists() or dest.is_relative_to(base):
        raise ValueError("Choose a new destination outside the base package")
    manifest = json.loads((base / "package-manifest.json").read_text("utf-8-sig"))
    for rel in ("FxStudio.Agent.exe", "ProfileStudio/ProfileStudio.exe", "ProfileStudio/package-manifest.json",
                "runtime/gdb/bin/gdb.exe", "sdk/native/host/python/python.exe", "loader-artifacts/FlashLd.g1a"):
        source_file(base, rel)
    for row in manifest["files"]:
        rel = row["path"]
        src = source_file(base, rel)
        if digest(src) != row["sha256"]:
            raise ValueError("Base package differs: " + rel)
        if rel.startswith("runtime/emulator/storage/"):
            continue
        target = dest / "Studio" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    (dest / "Studio" / "win32-base.json").write_text(json.dumps({
        "base": manifest["name"], "baseManifestSha256": digest(base / "package-manifest.json")
    }, indent=2), encoding="utf-8")

def finish(a):
    dest = a.dest.resolve()
    target = dest / "Studio"
    if not (target / "win32-base.json").is_file():
        raise ValueError("Run the base step first")
    # Use the merged SDK desktop + Agent publish. Never install console framework
    # facade DLLs over the desktop framework used by the classic UI.
    for p in records(a.classic):
        out = target / p.relative_to(a.classic)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
    for suffix in (".exe", ".dll", ".deps.json", ".runtimeconfig.json"):
        name = "FxStudio.Win32Host" + suffix
        shutil.copy2(a.host / name, target / name)
    if digest(a.host / "FxStudio.Core.dll") != digest(target / "FxStudio.Core.dll"):
        raise ValueError("Host and SDK were built against different Core binaries")
    update_native_service(target)
    copy_development_runtime(ROOT, target)
    wsl = target / "tooling/wsl"
    wsl.mkdir(parents=True, exist_ok=True)
    for name in ("build-project", "compiler-launcher", "cancel-build"):
        script = (ROOT / "tooling" / (name + ".py")).read_bytes().replace(b"\r\n", b"\n")
        (wsl / name).write_bytes(script)
    copy_loader_runtime(ROOT, a.artifacts, target)
    copy_verified_emulator(ROOT, a.emulator, target / "runtime/emulator")
    emulator = target / "runtime/emulator"
    historical = target / "validation/baseline-emulator"
    for name in ("LOCAL-UPDATE.json", "VALIDATION-OS-MAP.json"):
        if (emulator / name).is_file():
            historical.mkdir(parents=True, exist_ok=True)
            (emulator / name).replace(historical / name)
    for name in ("syscall-coverage.json", "SYSCALL-COVERAGE.md"):
        shutil.copy2(ROOT / "probes/emulator" / name, emulator / name)
    exclude = shutil.ignore_patterns("__pycache__", "*.pyc", ".fxstudio", "build", "build-*", "obj", "bin", ".git")
    for name in ("docs", "skills", "scaffolds"):
        shutil.copytree(ROOT / name, target / name, dirs_exist_ok=True, ignore=exclude)
    shutil.copy2(ROOT / "tooling/engineering.py", target / "automation/engineering.py")
    shutil.copy2(ROOT / "README.md", target / "README.md")
    shutil.copy2(ROOT / "src/FxStudio.App/CalculatorKnowledge.json", target / "docs")
    shutil.copy2(ROOT / "probes/emulator/syscall-coverage.json", target / "docs")
    prepare(a.deps)
    editor = target / "editor"
    editor.mkdir(exist_ok=True)
    for name in ("Scintilla.dll", "Lexilla.dll", "Scintilla.License.txt", "Lexilla.License.txt", "json.LICENSE"):
        shutil.copy2(a.deps / name, editor / name)
    shutil.copy2(a.native, dest / "FxStudio.Win32.exe")
    shutil.copy2(HERE / "README.md", dest / "使用说明.md")
    shutil.copy2(HERE / "start.html", dest / "开始使用.html")
    # Include editable Win32 sources and every pinned editor input for offline rebuilding.
    src = target / "sources/current"
    shutil.copytree(HERE, src / "desktop/Win32", dirs_exist_ok=True, ignore=exclude)
    for name in ("FxStudio.Core", "FxStudio.Automation", "FxStudio.App", "FxStudio.Agent"):
        shutil.copytree(ROOT / "src" / name, src / "src" / name, dirs_exist_ok=True, ignore=exclude)
    (src / "probes/emulator").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "probes/emulator/syscall-coverage.json", src / "probes/emulator")
    for name in BRIDGE_SOURCES:
        relative = (ROOT / "probes/emulator" / name).resolve().relative_to(ROOT)
        shutil.copy2(ROOT / relative, src / relative)
    for name in ("debugger-hooks.patch", "runtime-compat.patch"):
        shutil.copy2(emulator / name, src / "probes/emulator" / name)
    upstream = Path("third_party/emuCasioCalc")
    shutil.copytree(ROOT / upstream / "src", src / upstream / "src", dirs_exist_ok=True)
    shutil.copy2(ROOT / upstream / "LICENSE", src / upstream)
    (src / upstream / "SOURCE-ORIGIN.json").write_text(json.dumps({"revision": UPSTREAM}) + "\n", encoding="utf-8")
    (src / "tooling").mkdir(exist_ok=True)
    for name in ("package_components.py", "check_emulator_build.py", "build-native.py", "build-project.py", "compiler-launcher.py", "cancel-build.py"):
        shutil.copy2(ROOT / "tooling" / name, src / "tooling")
    shutil.copy2(ROOT / "LICENSE", src)
    dep_src = src / "editor-inputs"
    dep_src.mkdir(exist_ok=True)
    for name in INPUTS:
        shutil.copy2(a.deps / name, dep_src / name)
    shutil.copy2(ROOT / "global.json", src)
    if a.stage_only:
        return
    inventory = target / "package-manifest.json"
    inventory.write_text(json.dumps({"schemaVersion": 1, "name": "Fx Studio Win32 SDK payload", "files": [
        {"path": p.relative_to(target).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
        for p in records(target) if p != inventory]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    archive = dest.with_suffix(".zip")
    partial = archive.with_suffix(".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as z:
        for p in records(dest):
            compress = zipfile.ZIP_STORED if p.suffix.lower() in (".zip", ".jar", ".jmod", ".gz", ".xz", ".png") else zipfile.ZIP_DEFLATED
            z.write(p, dest.name + "/" + p.relative_to(dest).as_posix(), compress_type=compress)
    with zipfile.ZipFile(partial) as z:
        bad = z.testzip()
        if bad: raise ValueError("Archive failed CRC: " + bad)
    os.replace(partial, archive)
    print(archive, archive.stat().st_size, digest(archive), flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="mode", required=True)
    base = subs.add_parser("base")
    base.add_argument("--base", type=Path, required=True)
    base.add_argument("--dest", type=Path, required=True)
    pack = subs.add_parser("pack")
    pack.add_argument("--stage-only", action="store_true", help="Prepare a runnable tree for desktop acceptance testing")
    for arg in ("dest", "classic", "host", "native", "deps", "artifacts", "emulator"):
        pack.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "base": assemble_base(args.base.resolve(), args.dest.resolve())
    else: finish(args)
