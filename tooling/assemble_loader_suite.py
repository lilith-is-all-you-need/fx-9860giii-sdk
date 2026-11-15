"""Create a new offline package using an existing complete SDK; never alter it."""
import argparse,hashlib,json,os,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def replace(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.suite-new')
    shutil.copy2(source,temporary);os.replace(temporary,destination)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-package','destination','published-app','artifacts'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();base=a.base_package.resolve();out=a.destination.resolve()
    if out.exists() or out.is_relative_to(base):raise ValueError('Choose a new folder outside the base package')
    for rel in ('FxStudio.Agent.exe','sdk/native/host/python/python.exe','package-manifest.json'):
        if not (base/rel).is_file():raise ValueError('Incomplete base SDK: '+rel)
    manifest=json.loads((base/'package-manifest.json').read_text(encoding='utf-8-sig'))
    for record in manifest['files']:
        if digest(base/record['path'])!=record['sha256']:raise ValueError('Base package differs: '+record['path'])
    out.mkdir(parents=True)
    # Keep the package independent: editing either installation cannot change
    # the other's SDK files. Replacements below still publish atomically.
    for source in base.rglob('*'):
        if source.is_file():
            dest=out/source.relative_to(base);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest)
    for name in ('FxStudio.exe','FxStudio.dll','FxStudio.pdb','FxStudio.deps.json','FxStudio.runtimeconfig.json'):
        replace(a.published_app/name,out/name)
    for rel in ('tooling/loader_suite.py','profiles/registry.json','probes/native-loader/tools/prepare.py','probes/mapped-loader/tools/prepare.py','loader-components.lock.json'):
        replace(ROOT/rel,out/rel)
    for name in ('Loader.g1a','KLoad.g1a','KhiMap.g1a','manifest.json'):
        replace(a.artifacts/name,out/'loader-artifacts'/name)
    replace(ROOT/'probes/emulator/build/FxEmulator.exe',out/'runtime/emulator/FxEmulator.exe')
    replace(ROOT/'probes/emulator/build/BUILD-MANIFEST.json',out/'runtime/emulator/BUILD-MANIFEST.json')
    notes=out/'Loader套件说明.txt'
    notes.write_text('启动 FxStudio.exe。工具 → 为 Loader 准备 G1A；帮助 → 计算器资料。\n'
        '输出目录中的 calculator 文件夹才是计算器安装文件。其余为电脑端报告和 profile。\n'
        'candidate 表示可测试候选，仍需实机验收；needs-review 表示尚不能直接执行。\n'
        '小文件 RAM 装载还受实际可用堆限制；不按 2 MB 简单判断。\n'
        '原版 KhiCAS 使用 KLoad；699 页的源码接入 Giac 版本使用 KhiMap。两者不可混用。\n'
        '本目录是独立的新版本，原安装包保留。\n',encoding='utf-8-sig')
    records=[{'path':x.relative_to(out).as_posix(),'bytes':x.stat().st_size,'sha256':digest(x)}
             for x in sorted(out.rglob('*')) if x.is_file() and x.name!='package-manifest.json']
    temporary=out/'package-manifest.suite-new'
    temporary.write_text(json.dumps({'schemaVersion':1,'name':out.name,'files':records},indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,out/'package-manifest.json')
    print(json.dumps({'package':str(out),'files':len(records)},ensure_ascii=False))

if __name__=='__main__':main()
