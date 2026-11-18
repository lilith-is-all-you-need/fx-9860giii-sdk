"""Export SDK snapshots of the emulator and ordinary Loader.

For current updates, import fx_universal_loader via sync_loader_components.py.

Never copies firmware, third-party G1As, build output, trace files, or user settings.
FxStudio keeps verified source snapshots so offline use requires no Git/network.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SUFFIXES={'.c','.h','.cpp','.hpp','.S','.ld','.cmake','.py','.ps1','.md','.json','.png','.patch','.txt','.cs','.xaml','.csproj','.manifest','.java','.xml'}
IGNORED={'build','.fxstudio','__pycache__','evidence','graphics-audit','bin','obj','.vs'}

def files(folder):
    for p in (ROOT/folder).rglob('*'):
        rel=p.relative_to(ROOT/folder)
        if p.is_file() and not IGNORED.intersection(rel.parts) and (p.suffix in SUFFIXES or p.name=='CMakeLists.txt'):
            yield str(p.relative_to(ROOT)).replace('\\','/')

def sources(kind):
    if kind=='emulator':
        return sorted(set(files('probes/emulator'))|{'probes/os-map-profile.h','probes/os-map-hashes.h',
            'probes/file-map-probe/src/os-map-profile.h','probes/file-map-probe/src/os-map-hashes.h'})
    if kind=='loader':
        return sorted(set(files('probes/native-loader'))|set(files('probes/storage-loader'))|set(files('profiles'))|set(files('desktop/ProfileStudio'))|set(files('sdk/caller-session'))|set(files('tooling/ghidra'))|{'tooling/loader_suite.py','tooling/profile_job.py','tooling/bundle_v2.py','tooling/package_profile_studio.py','tooling/package_components.py','tests/test_profile_job.py','tests/test_loader_suite.py','tests/test_flash_profiles.py','tests/test_caller_session.py','profiles/registry.json',
            'probes/mapped-loader/tools/prepare.py'})
    raise ValueError('Unknown component: '+kind)

def export(kind, destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    copied={}
    for rel in sources(kind):
        exported=rel
        p=destination/exported;p.parent.mkdir(parents=True,exist_ok=True)
        if p.suffix=='.png':shutil.copyfile(ROOT/rel,p)
        else:p.write_text((ROOT/rel).read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        copied[exported]=hashlib.sha256(p.read_bytes()).hexdigest()
    shutil.copyfile(ROOT/'LICENSE',destination/'LICENSE')
    if kind!='emulator':
        hardware=ROOT/'docs/loader'/('HARDWARE-'+('ram' if kind=='loader' else 'mapped')+'-20261117.md')
        shutil.copyfile(hardware,destination/'HARDWARE-20261117.md')
    (destination/'.gitignore').write_text('**/__pycache__/\n**/.fxstudio/\n**/build/\n**/evidence/\n**/bin/\n**/obj/\n**/.vs/\nloader-artifacts/\n*.zip\n*.elf\n*.g1a\n*.bin\n*.log\n',encoding='utf-8')
    (destination/'source-manifest.json').write_text(json.dumps({'schemaVersion':1,'component':kind,'files':copied},indent=2)+'\n',encoding='utf-8')
    (destination/'.gitattributes').write_text('* text=auto eol=lf\n*.png binary\n',encoding='utf-8')
    readmes={
        'emulator':'''# fx9860-emulator

Windows SH7305 emulator, GDB remote bridge, FX syscall models and fault evidence.
This is a functional HLE model, not a full Casio OS implementation.

```
git submodule update --init
pwsh ./probes/emulator/test-runtime.ps1 -Compiler C:/msys64/mingw64/bin/gcc.exe -Python python
```

Output: `probes/emulator/build/FxEmulator.exe`. CPU, runtime, MMU/cache, syscall,
recovery and guest-refill tests run locally and in Windows CI. Optional firmware
tests use `FX_TEST_FIRMWARE`; no proprietary OS image is distributed.

Guest RAM VBR refill and fault retry regressions cover automatic external-file
execution beyond the OS 2 MiB window. The OS table itself remains 512 pages.

See [backend documentation](probes/emulator/README.md) and
[coverage](probes/emulator/SYSCALL-COVERAGE.md). Upstream emuCasioCalc is pinned as
a submodule; retain its MIT and font licenses when distributing a binary.
FxStudio integrates a version-pinned source snapshot; this repository owns the
emulator component. Shared OS profile headers are hash-checked in that snapshot.
''',
        'loader':'''# fx9860-loader

Offline G1A preparation and generic Flash/RAM loaders. Standard-library Python;
no LLM service or network is required for analysis or conversion.

```
python tooling/loader_suite.py input.g1a --output new-result
python tooling/loader_suite.py --batch jobs.json --artifacts C:/LoaderSuite/loader-artifacts
python -m unittest discover -s tests -v
python probes/native-loader/tools/test_prepare.py
```

The converter preserves every original byte, emits page hashes and instruction
evidence, and uses the generic Flash backend for ordinary G1As within 2 MiB.
No program whitelist is needed for that backend. Structurally unsupported inputs
produce a report; accepted inputs remain test candidates, not a hardware guarantee. Exit codes:
0 = candidate bundle, 2 = analysis/profile only, 1 = error.

Build `probes/storage-loader` with the FxStudio offline SDK (target `flashloader`).
See its README and VALIDATION.json for memory, callback and hardware limitations.
The optional legacy RAM backend is `probes/native-loader` (target `loader`).
Put `Loader.g1a` and the sibling project's `KLoad.g1a` in `loader-artifacts/`
with `manifest.json` hashes; ordinary bundles require `FlashLd.g1a` there as well.
The calculator reads the generated index and profiles and uses EXE to launch.

RAM images are limited to 160 KiB *and* available contiguous heap, which may be
much smaller on hardware. The mapped KhiCAS adapter is exact-version only.
Hardware rejected Fruit and Minesweeper image allocations; their RAM profiles
are blocked only for RAM; generic Flash candidates use a smaller resident allocation.
See HARDWARE-20261117.md for the historical returned evidence and limits.
FxStudio includes a separate oversized source example under sdk/examples/oversized-loader.

Optional review JSON requires schemaVersion=1, exact sha256, backend=ram,
memoryReviewed=true, callbacksReviewed=true and forbiddenPhysicalRam ranges.
It is data, never executed as a script. This is an expert review record, not
a self-issued hardware compatibility certificate.

Batch JSON is an array of source/output/optional profile/reviewProfile objects;
paths resolve relative to the batch file. Existing outputs are never overwritten.
Original commercial/user G1As are not distributed. Code is MIT.

Shared mapped profile encoder is a synchronized snapshot from the large-loader
component. Integration checksums are recorded in source-manifest.json.
'''}
    (destination/'README.md').write_text(readmes[kind],encoding='utf-8')
    workflow=destination/'.github/workflows/check.yml';workflow.parent.mkdir(parents=True)
    if kind=='emulator':
        shutil.copyfile(ROOT/'.github/workflows/emulator.yml',workflow)
        body=workflow.read_text();body=body[:body.index('      - name: Verify native Loader')]
        # Standalone repository changes always affect this component.
        body='\n'.join(line for line in body.splitlines() if 'paths:' not in line)+'\n'
        workflow.write_text(body)
        shutil.copyfile(ROOT/'.gitmodules',destination/'.gitmodules')
    else:
        commands='python -m unittest discover -s tests -v\n          python probes/native-loader/tools/test_prepare.py'
        workflow.write_text('name: Offline contracts\non: [push, pull_request, workflow_dispatch]\npermissions:\n  contents: read\njobs:\n  contracts:\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803\n        with:\n          persist-credentials: false\n      - run: |\n          '+commands+'\n')
    return copied

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);a=p.parse_args()
    for kind in ('emulator','loader'):
        result=export(kind,a.destination/('fx9860-'+kind));print(kind,len(result))
