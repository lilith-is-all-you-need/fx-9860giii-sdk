"""Build isolated native-code SDK libraries; never installs over the shared SDK."""
from pathlib import Path
import difflib,hashlib,json,os,shutil,subprocess,tarfile
ROOT=Path(__file__).resolve().parents[2]
SDK=Path.home()/'.codex-build-envs/native-sdk-20261114/prefix'
WORK=Path.home()/'.codex-build-envs/native-sdk-20261114/native-libs-no-lto'
OUT=ROOT/'dist-toolchain/native-fxsdk/target-libs'
for path in (WORK,OUT):path.mkdir(parents=True,exist_ok=True)
SOURCES=ROOT/'dist-toolchain/sources/sdk'
env=dict(os.environ,PATH=';'.join(map(str,[SDK/'bin',SDK/'host/python',SDK/'host/cmake/bin',SDK/'host/ninja',Path(os.environ['SYSTEMROOT'])/'System32'])),PYTHONUTF8='1')
manifest={'purpose':'isolated native-code SDK library fallback; shared prefix unchanged','sdk':str(SDK),'work':str(WORK),'libraries':[]}
patches=[]
def run(args,log):
    args=list(map(str,args));manifest.setdefault('commands',[]).append(args)
    subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
try:
    for component,archive,library in [('fxlibc','fxlibc-e2f458fa3d88.tar.gz','libc.a'),('gint','gint-badbd0fd2bd8.tar.gz','libgint-fx.a')]:
        source_base=WORK/'source'/component;source_base.mkdir(parents=True,exist_ok=True)
        with tarfile.open(SOURCES/archive) as tar:
            tar.extractall(source_base,filter='data')
        source=next(p.parent for p in source_base.glob('*/CMakeLists.txt'))
        cmakelist=source/'CMakeLists.txt'
        original=cmakelist.read_text(encoding='utf-8')
        modified=original.replace('set(FXLIBC_LTO 1)','set(FXLIBC_LTO 0)').replace('-mtas -flto)','-mtas -fno-lto)')
        # Plain native object archives do not need gcc-ar's LTO plugin probing.
        modified=modified.replace('${CMAKE_C_COMPILER_AR}', '${CMAKE_AR}').replace('${CMAKE_C_COMPILER_RANLIB}', '${CMAKE_RANLIB}')
        cmakelist.write_text(modified,encoding='utf-8',newline='\n')
        patches.extend(difflib.unified_diff(original.splitlines(True),modified.splitlines(True),fromfile='a/'+component+'/CMakeLists.txt',tofile='b/'+component+'/CMakeLists.txt'))
        build=WORK/('build-'+component)
        log_path=OUT/(component+'-build.log')
        with log_path.open('w',encoding='utf-8') as log:
            args=[SDK/'host/cmake/bin/cmake.exe','-S',source,'-B',build,'-G','Ninja','-DCMAKE_MAKE_PROGRAM='+str(SDK/'host/ninja/ninja.exe'),'-DCMAKE_TOOLCHAIN_FILE='+str(SDK/'lib/cmake/fxsdk/FX9860G.cmake'),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_INSTALL_PREFIX='+str(WORK/'private-install')]
            if component=='fxlibc':args+=['-DFXLIBC_TARGET=gint']
            run(args,log)
            run([SDK/'host/cmake/bin/cmake.exe','--build',build,'--parallel','8'],log)
        shutil.copy2(build/library,OUT/library)
        shutil.copy2(build/'compile_commands.json',OUT/(component+'-compile_commands.json'))
        if component=='gint':
            shutil.copy2(build/'fx9860g.ld',OUT/'fx9860g.ld')
            shutil.copy2(build/'include/gint/config.h',OUT/'gint-config.h')
        sections=subprocess.check_output([str(SDK/'bin/sh-elf-readelf.exe'),'-SW',str(build/library)],env=env,text=True,errors='replace')
        if '.gnu.lto_' in sections: raise RuntimeError(component+' still has LTO sections')
        manifest['libraries'].append({'component':component,'sourceArchive':archive,'sourceSha256':hashlib.sha256((SOURCES/archive).read_bytes()).hexdigest(),'output':library,'bytes':(OUT/library).stat().st_size,'sha256':hashlib.sha256((OUT/library).read_bytes()).hexdigest(),'containsLtoSections':False})
        print('BUILT '+component+' native machine-code archive; not installed',flush=True)
finally:
    (OUT/'native-target-libs.patch').write_text(''.join(patches),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
