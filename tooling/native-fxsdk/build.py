"""Build native fxgxa and package patched fxconv/CMake modules; no WSL."""
from pathlib import Path
import difflib,hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'dist-toolchain/native-fxsdk'
PREFIX=OUT/'prefix'
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'.codex-build-envs/native-sdk-20261114/source/fxSDK'
if not SOURCE.is_dir(): SOURCE=OUT/'upstream-fxSDK'
GINT_MODULE=OUT/'upstream-gint/FindGint.cmake'
if not GINT_MODULE.is_file():
    GINT_MODULE.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(Path.home()/'.codex-build-envs/fxsdk-dev-20261114/rootfs/root/.local/lib/cmake/fxsdk/FindGint.cmake',GINT_MODULE)
MINGW=Path('C:/msys64/mingw64')
BUILD=OUT/'build'
for directory in (BUILD,PREFIX/'bin',PREFIX/'lib/cmake/fxsdk',PREFIX/'licenses'):
    directory.mkdir(parents=True,exist_ok=True)
if SOURCE.resolve()!=(OUT/'upstream-fxSDK').resolve(): shutil.copytree(SOURCE,OUT/'upstream-fxSDK',dirs_exist_ok=True)
shutil.copy2(SOURCE/'LICENSE',PREFIX/'licenses/fxSDK-LICENSE.txt')
for library in ('libpng','zlib'):
    shutil.copy2(MINGW/'share/licenses'/library/'LICENSE',PREFIX/'licenses'/(library+'-LICENSE.txt'))
patches=[]
def changed(relative,text,target):
    original=(SOURCE/relative).read_text(encoding='utf-8')
    patches.extend(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative))
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(text,encoding='utf-8',newline='\n')

src=BUILD/'fxgxa'
shutil.copytree(SOURCE/'fxgxa',src,dirs_exist_ok=True)
relative='fxgxa/main.c'
text=(SOURCE/relative).read_text(encoding='utf-8').replace('int main(int argc, char **argv)','int fxgxa_main(int argc, char **argv)')
for field,condition in (('icon','w == 30 && (h == 17 || h == 19)'),('icon_uns','w == 92 && h == 64'),('icon_sel','w == 92 && h == 64')):
    anchor=f'uint8_t *rgb24 = icon_load(fields->{field}, &w, &h);'
    text=text.replace(anchor,anchor+f'\n\t\tif(!rgb24 || !({condition})) {{ fprintf(stderr, "error: invalid {field} image dimensions or unreadable PNG\\n"); free(rgb24); exit(1); }}')
text=text.replace('save_gxa(output, gxa, size);','if(save_gxa(output, gxa, size)) { free(gxa); return 1; }')
text=text.replace('save_gxa(output ? output : alloc, gxa, size);','if(save_gxa(output ? output : alloc, gxa, size)) { free(gxa); free(alloc); return 1; }')
for call in ('icon_save(output ? output : alloc, rgb24, 30, 19)','icon_save(output_uns, rgb24_uns, 92, 64)','icon_save(output_sel, rgb24_sel, 92, 64)'):
    text=text.replace(call+';',f'if({call}) return 1;')
changed(relative,text,src/'main.c')
relative='fxgxa/file.c'
text=(SOURCE/relative).read_text(encoding='utf-8').replace('fclose(fp);\t','if(fp) fclose(fp);\t').replace('if(status < 0) fail','if(status <= 0) fail')
text=text.replace('filesize = ftell(fp);','filesize = ftell(fp);\n\tif(filesize < 0 || filesize > 64*1024*1024 || (!header && filesize < 512)) fail("invalid input size for %s", filename);')
text=text.replace('void *ret = load(filename, size, 0, 0);\n\tif(ret) invert_header(ret);','size_t loaded = 0;\n\tvoid *ret = load(filename, &loaded, 0, 0);\n\tif(ret) {\n\t\tinvert_header(ret);\n\t\tif((!is_g1a(ret) && !is_g3a(ret)) || (is_g3a(ret) && loaded < 0x7004)) { fprintf(stderr, "error: invalid or truncated add-in header\\n"); free(ret); return NULL; }\n\t}\n\tif(size) *size = loaded;')
changed(relative,text,src/'file.c')
relative='fxgxa/icon.c'
changed(relative,(SOURCE/relative).read_text(encoding='utf-8').replace('png_image_free(&img);','png_image_free(&img);\n    fx_png_close();'),src/'icon.c')

# Close temporary files before child processes read them. Constant local names
# avoid Windows drive/backslash-specific objcopy symbol names.
relative='fxconv/fxconv.py'
text=(SOURCE/relative).read_text(encoding='utf-8')
begin=text.index('\t# Generate data - in <output>')
end=text.index('\ndef elf_multi',begin)
replacement='''\t# Windows-native temporary files are closed before invoking binutils.
\toutput = os.path.abspath(output)
\twith tempfile.TemporaryDirectory(prefix="fxconv-") as temporary:
\t\tif data is not None:
\t\t\twith open(os.path.join(temporary, "blob"), "wb") as stream:
\t\t\t\tstream.write(data)
\t\t\tobjcopy_args = [f"{toolchain}objcopy", "-I", "binary", "-O", outputtarget,
\t\t\t\t"--binary-architecture", arch, "--file-alignment", "4",
\t\t\t\t"--rename-section", f".data={section}",
\t\t\t\t"--redefine-sym", f"_binary_blob_start={symbol}",
\t\t\t\t"--redefine-sym", f"_binary_blob_end={symbol}_end",
\t\t\t\t"--redefine-sym", f"_binary_blob_size={symbol}_size",
\t\t\t\t"blob", output if not assembly else "blob.o"]
\t\t\tproc = subprocess.run(objcopy_args, cwd=temporary)
\t\t\tif proc.returncode: raise FxconvError(f"objcopy returned {proc.returncode}")
\t\tif assembly:
\t\t\twith open(os.path.join(temporary, "asset.s"), "w", encoding="utf-8", newline="\\n") as stream:
\t\t\t\tstream.write(assembly)
\t\t\tproc = subprocess.run([f"{toolchain}as", "-c", "asset.s", "-o",
\t\t\t\toutput if data is None else "asset.o"], cwd=temporary)
\t\t\tif proc.returncode: raise FxconvError(f"as returned {proc.returncode}")
\t\tif data is not None and assembly:
\t\t\tproc = subprocess.run([f"{toolchain}ld", "-r", "blob.o", "asset.o", "-o", output], cwd=temporary)
\t\t\tif proc.returncode: raise FxconvError(f"ld returned {proc.returncode}")

'''
changed(relative,text[:begin]+replacement+text[end:],PREFIX/'bin/fxconv.py')
shutil.copy2(SOURCE/'fxconv/fxconv-main.py',PREFIX/'bin/fxconv-main.py')
shutil.copy2(HERE/'fxsdk-main.py',PREFIX/'bin/fxsdk-main.py')
modules=PREFIX/'lib/cmake/fxsdk'
for file in (SOURCE/'fxsdk/cmake').glob('*'): shutil.copy2(file,modules/file.name)
for name in ('FX9860G.cmake','GenerateG1A.cmake','FindSimpleLibrary.cmake'):
    changed('fxsdk/cmake/'+name,(HERE/name).read_text(encoding='utf-8'),modules/name)
relative='fxsdk/cmake/CMakeDetermineFXCONVCompiler.cmake'
text=(SOURCE/relative).read_text(encoding='utf-8').replace('set(FXCONV_COMPILER_NAME $ENV{FXCONV_PATH})','if(NOT FXCONV_COMPILER_NAME)\n  set(FXCONV_COMPILER_NAME "$ENV{FXCONV_PATH}")\nendif()')
changed(relative,text,modules/'CMakeDetermineFXCONVCompiler.cmake')
relative='fxsdk/cmake/Fxconv.cmake'
text=(SOURCE/relative).read_text(encoding='utf-8').replace('"--converters=${FXCONV_CONVERTERS}"','"\\\"--converters=${FXCONV_CONVERTERS}\\\""')
changed(relative,text,modules/'Fxconv.cmake')
# Gint's installed module also depended on sed and the fxsdk shell entry point.
original=GINT_MODULE.read_text(encoding='utf-8')
text=original
start=text.index('execute_process(\n  COMMAND fxsdk path include')
end=text.index('set(GINT_CONFIG_PATH',start)
text=text[:start]+text[end:]
start=text.index('    execute_process(\n      COMMAND sed')
end=text.index('\n  endif()',start)
text=text[:start]+'''    file(READ "${GINT_CONFIG_PATH}" GINT_CONFIG_CONTENT)
    string(REGEX MATCH "#define[ \\t]+GINT_VERSION[ \\t]+\\\"([^\\\"]+)\\\"" MATCH "${GINT_CONFIG_CONTENT}")
    set(GINT_VERSION "${CMAKE_MATCH_1}")'''+text[end:]
(modules/'FindGint.cmake').write_text(text,encoding='utf-8',newline='\n')
patches.extend(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/gint/FindGint.cmake',tofile='b/gint/FindGint.cmake'))
(OUT/'native-host.patch').write_text(''.join(patches),encoding='utf-8')

env=dict(os.environ,PATH=str(MINGW/'bin')+';'+os.environ['PATH'])
commands=[]
with (OUT/'build.log').open('w',encoding='utf-8') as log:
    def run(args):
        # MinGW ld does not accept UTF-8 absolute output paths. Relative paths
        # keep all generated names ASCII while cwd is supplied as Unicode.
        args=[os.path.relpath(a,ROOT) if isinstance(a,Path) and a.is_relative_to(ROOT) else str(a) for a in args]
        commands.append(args)
        subprocess.run(args,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    common=[MINGW/'bin/gcc.exe','-std=gnu11','-O2','-Wall','-Wextra','-static','-municode']
    run(common+['-include',HERE/'win_compat.h','-I',src,'-I',MINGW/'include',*[src/name for name in ('dump.c','edit.c','file.c','icon.c','main.c','util.c')],HERE/'win_compat.c',MINGW/'lib/libpng.a',MINGW/'lib/libz.a','-o',PREFIX/'bin/fxgxa.exe'])
    run(common+[HERE/'python_launcher.c','-o',PREFIX/'bin/fxconv.exe'])
    run(common+['-DSCRIPT=L"fxsdk-main.py"',HERE/'python_launcher.c','-o',PREFIX/'bin/fxsdk.exe'])
shutil.copy2(PREFIX/'bin/fxgxa.exe',PREFIX/'bin/fxg1a.exe')
manifest={'fxsdkVersion':'2.11.0','fxsdkRevision':'4d7eab028ef1df83ead3edb1c440055190d1ed98','source':str(SOURCE),
          'sourceFiles':{p.relative_to(SOURCE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file()},
          'staticLibraries':{name:{'path':str(MINGW/'lib'/name),'sha256':hashlib.sha256((MINGW/'lib'/name).read_bytes()).hexdigest()} for name in ('libpng.a','libz.a')},
          'commands':commands,'files':{str(p.relative_to(PREFIX)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (PREFIX/'bin').iterdir() if p.is_file()}}
(OUT/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Native fxSDK host tools built at '+str(PREFIX))
