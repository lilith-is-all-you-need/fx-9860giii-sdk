"""Create a new offline package using an existing complete SDK; never alter it."""
import argparse,hashlib,json,os,shutil
from pathlib import Path
from package_components import copy_loader_runtime, copy_development_runtime, loader_artifact_hashes
from check_emulator_build import verify_emulator_build, copy_verified_emulator

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
    p.add_argument('--emulator-build',type=Path,default=ROOT/'probes/emulator/build')
    a=p.parse_args();base=a.base_package.resolve();out=a.destination.resolve()
    if out.exists() or out.is_relative_to(base):raise ValueError('Choose a new folder outside the base package')
    for rel in ('FxStudio.Agent.exe','sdk/native/host/python/python.exe','package-manifest.json'):
        if not (base/rel).is_file():raise ValueError('Incomplete base SDK: '+rel)
    manifest=json.loads((base/'package-manifest.json').read_text(encoding='utf-8-sig'))
    for record in manifest['files']:
        if digest(base/record['path'])!=record['sha256']:raise ValueError('Base package differs: '+record['path'])
    # Use Publish-App.ps1's merged output so Core and the automation host cannot
    # silently remain at the base package's old version.
    for name in ('FxStudio.exe','FxStudio.Core.dll','FxStudio.Automation.dll','FxStudio.Agent.exe'):
        if not (a.published_app/name).is_file():raise ValueError('Provide the merged desktop/Agent publish directory: '+name)
    verify_emulator_build(ROOT,a.emulator_build)
    loader_artifact_hashes(a.artifacts)
    out.mkdir(parents=True)
    # Keep the package independent: editing either installation cannot change
    # the other's SDK files. Replacements below still publish atomically.
    for source in base.rglob('*'):
        if source.is_file():
            dest=out/source.relative_to(base);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest)
    for source in a.published_app.rglob('*'):
        if source.is_file():replace(source,out/source.relative_to(a.published_app))
    copy_loader_runtime(ROOT,a.artifacts,out)
    copy_development_runtime(ROOT,out)
    for folder in ('docs','skills','scaffolds'):
        shutil.copytree(ROOT/folder,out/folder,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc','.fxstudio','build*'))
    replace(ROOT/'tooling/engineering.py',out/'automation/engineering.py')
    copy_verified_emulator(ROOT,a.emulator_build,out/'runtime/emulator')
    notes=out/'Loader套件说明.txt'
    notes.write_text('启动 FxStudio.exe。工具 → 为 Loader 准备 G1A；帮助 → 计算器资料。\n'
        '输出目录中的 calculator 文件夹才是计算器安装文件。其余为电脑端报告和 profile。\n'
        'candidate 表示可测试候选，仍需实机验收；needs-review 表示尚不能直接执行。\n'
        '小文件 RAM 装载还受实际可用堆限制；不按 2 MB 简单判断。\n'
        '原版 KhiCAS 使用 KLoad；699 页的源码接入 Giac 版本使用 KhiMap。两者不可混用。\n'
        '本目录是独立的新版本，原安装包保留。\n',encoding='utf-8-sig')
    (out/'CURRENT-SOURCE-NOTICE.txt').write_text(
        'Fx Studio local development assembly / 本地开发组合包\n\n'
        'This directory combines an earlier validated base runtime with newly published application,\n'
        'Loader, migration/resource tools, documentation and a source-verified emulator.\n'
        'The sources/ archive and validation/ records inherited from the base describe that earlier\n'
        'baseline. They are NOT the matching source companion or acceptance evidence for this\n'
        'updated assembly. Do not redistribute them as if they were current validation.\n'
        'Generate a fresh companion with tooling/collect_public_sources.py after the final source\n'
        'revision is fixed, and perform acceptance tests for the resulting current package.\n'
        'runtime/emulator/SOURCE-VALIDATION.json checks source/binary identity only.\n'
        'package-manifest.json checks file integrity; neither record certifies device behavior.\n\n'
        'sources/ 中沿用的归档及 validation/ 中的旧报告仅是基础包的历史记录，\n'
        '不代表当前新版应用的对应源码或验收结果。当前组合包需使用最终源码重新\n'
        '生成配套源码归档，并单独验证；请勿覆盖旧 Release 附件或套用旧通过结论。\n',
        encoding='utf-8-sig')
    records=[{'path':x.relative_to(out).as_posix(),'bytes':x.stat().st_size,'sha256':digest(x)}
             for x in sorted(out.rglob('*')) if x.is_file() and x.name!='package-manifest.json']
    temporary=out/'package-manifest.suite-new'
    temporary.write_text(json.dumps({'schemaVersion':1,'name':out.name,'files':records},indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,out/'package-manifest.json')
    print(json.dumps({'package':str(out),'files':len(records)},ensure_ascii=False))

if __name__=='__main__':main()
