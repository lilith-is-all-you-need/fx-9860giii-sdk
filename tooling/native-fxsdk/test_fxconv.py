"""Native binutils: binary data, PNG image, custom relocation, CMake FXCONV."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
TOOLS=ROOT/'dist-toolchain/native-fxsdk/prefix'
COMPILER=Path.home()/'.codex-build-envs/native-sdk-20261114/prefix'
WORK=Path.home()/'.codex-build-envs/native-sdk-20261114/fxconv-tests'
WORK.mkdir(parents=True,exist_ok=True)
for name in ('as','ld','objcopy','readelf','nm'):
    shutil.copy2(COMPILER/'bin'/('sh-elf-'+name+'.exe'),TOOLS/'bin'/('sh-elf-'+name+'.exe'))
shutil.copy2('C:/msys64/mingw64/bin/libwinpthread-1.dll',TOOLS/'bin/libwinpthread-1.dll')
env=dict(os.environ,PATH=str(TOOLS/'bin')+';'+str(Path(os.environ['SYSTEMROOT'])/'System32'),PYTHONUTF8='1')
checks=[]
log=[]
def run(args,cwd=WORK):
    result=subprocess.run(list(map(str,args)),cwd=cwd,env=env,encoding='utf-8',errors='replace',capture_output=True)
    log.append({'args':list(map(str,args)),'exitCode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    return result.stdout
def check(name): checks.append(name);print('PASS '+name)
try:
    fxconv=TOOLS/'bin/fxconv.exe'
    (WORK/'payload.bin').write_bytes(b'\x00\x01\x0a\xffabcdef')
    run([fxconv,'--binary','--fx','--toolchain=sh-elf','payload.bin','-o','payload.o','name:payload'])
    symbols=run([TOOLS/'bin/sh-elf-nm.exe','payload.o'])
    assert '_payload' in symbols and '_binary_' not in symbols,symbols
    run([TOOLS/'bin/sh-elf-objcopy.exe','-O','binary','payload.o','payload-roundtrip.bin'])
    assert (WORK/'payload-roundtrip.bin').read_bytes()==(WORK/'payload.bin').read_bytes()
    check('Binary bytes and requested symbol survive native objcopy')
    shutil.copy2(ROOT/'examples/counter-c/assets/icon.png',WORK/'icon.png')
    run([fxconv,'--bopti-image','--fx','--toolchain=sh-elf','icon.png','-o','image.o','name:image'])
    assert '_image' in run([TOOLS/'bin/sh-elf-nm.exe','image.o'])
    check('Pillow PNG to gint bopti image assembles into SuperH ELF')
    script=WORK/'custom-test.py'
    script.write_text("import fxconv\nfxconv.elf(b'\\x01\\x02\\x03\\x04', 'custom.o', '_bytes', toolchain='sh-elf', arch='sh3', assembly='.global _pointer\\n_pointer:\\n.long _bytes\\n')\n",encoding='utf-8')
    run([TOOLS/'host/python/python.exe','-X','utf8',script])
    relocs=run([TOOLS/'bin/sh-elf-readelf.exe','-r','custom.o'])
    assert '_bytes' in relocs
    check('Combined binary and assembly uses relocatable linker and preserves relocation')
    (WORK/'fxconv-metadata.txt').write_text('icon.png:\n  type: bopti-image\n  name: asset\n',encoding='utf-8')
    modules=(TOOLS/'lib/cmake/fxsdk').as_posix()
    (WORK/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.15)
project(NativeFxconv NONE)
list(PREPEND CMAKE_MODULE_PATH "{modules}")
set(FXCONV_COMPILER_NAME "{fxconv.as_posix()}")
set(FXSDK_PLATFORM fx)
include(Fxconv)
fxconv_declare_assets(icon.png WITH_METADATA)
add_library(assets OBJECT icon.png)
''',encoding='utf-8')
    run([TOOLS/'host/cmake/bin/cmake.exe','-S',WORK,'-B',WORK/'build','-G','Ninja','-DCMAKE_MAKE_PROGRAM='+str(TOOLS/'host/ninja/ninja.exe')])
    run([TOOLS/'host/cmake/bin/cmake.exe','--build',WORK/'build','--verbose'])
    assert (WORK/'build/CMakeFiles/assets.dir/icon.png.o').is_file()
    check('Native CMake FXCONV language and metadata dependency create an object')
    converters=WORK/'custom converters'
    converters.mkdir(exist_ok=True)
    (converters/'pass one.py').write_text('def convert(*args, **kwargs):\n    return None\n',encoding='utf-8')
    (converters/'second.py').write_text('def convert(*args, **kwargs):\n    return None\n',encoding='utf-8')
    cmake=WORK/'CMakeLists.txt'
    cmake.write_text(cmake.read_text(encoding='utf-8').replace('fxconv_declare_assets','fxconv_declare_converters("custom converters/pass one.py" "custom converters/second.py")\nfxconv_declare_assets'),encoding='utf-8')
    run([TOOLS/'host/cmake/bin/cmake.exe','-S',WORK,'-B',WORK/'build'])
    run([TOOLS/'host/cmake/bin/cmake.exe','--build',WORK/'build','--clean-first','--verbose'])
    assert (WORK/'build/CMakeFiles/assets.dir/icon.png.o').is_file()
    check('CMake custom converter list preserves spaces and semicolons')
    (WORK/'empty.bin').write_bytes(b'')
    result=subprocess.run([str(fxconv),'--binary','--fx','--toolchain=sh-elf','empty.bin','-o','empty.o','name:empty'],cwd=WORK,env=env,capture_output=True)
    assert result.returncode!=0,'Empty binary resource must not silently succeed without an object'
    check('Empty binary reports conversion failure instead of leaving an absent/stale object')
finally:
    (ROOT/'dist-toolchain/native-fxsdk/fxconv-test-results.json').write_text(json.dumps({'checks':checks,'count':len(checks),'runs':log},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
