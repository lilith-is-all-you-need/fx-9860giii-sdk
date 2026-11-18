"""Create a new offline package using an existing complete SDK; never alter it."""
import argparse,hashlib,json,os,shutil
from pathlib import Path
from package_components import copy_loader_runtime, copy_development_runtime, loader_artifact_hashes, public_component_sources, source_file
from check_emulator_build import verify_emulator_build, copy_verified_emulator

ROOT=Path(__file__).resolve().parents[1]

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def replace(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.suite-new')
    shutil.copy2(source,temporary);os.replace(temporary,destination)

def inherited_file(relative):
    # Product components are assembled afresh, including their sources and manifests.
    name = Path(relative).as_posix().lower()
    replaced = ('profilestudio/', 'loader-artifacts/', 'desktop/profilestudio/', 'sdk/fxlarge/',
                'sdk/examples/oversized-loader/', 'probes/extended-cas/', 'probes/extended-loader/',
                'probes/source-guest/', 'probes/mapped-loader/vendor/fxlarge/')
    return not name.startswith(replaced) and name not in {'tooling/ext_profile.py', 'tooling/hook_review.py', 'tests/test_hook_review.py'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-package','destination','published-app','artifacts'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--emulator-build',type=Path,default=ROOT/'probes/emulator/build')
    p.add_argument('--profile-studio',type=Path,help='Complete separately verified Profile Studio portable directory')
    a=p.parse_args();base=a.base_package.resolve();out=a.destination.resolve()
    if out.exists() or out.is_relative_to(base):raise ValueError('Choose a new folder outside the base package')
    for rel in ('FxStudio.Agent.exe','sdk/native/host/python/python.exe','package-manifest.json'):
        if not (base/rel).is_file():raise ValueError('Incomplete base SDK: '+rel)
    manifest=json.loads((base/'package-manifest.json').read_text(encoding='utf-8-sig'))
    for record in manifest['files']:
        source=source_file(base,record['path'])
        if digest(source)!=record['sha256']:raise ValueError('Base package differs: '+record['path'])
    # Use Publish-App.ps1's merged output so Core and the automation host cannot
    # silently remain at the base package's old version.
    for name in ('FxStudio.exe','FxStudio.Core.dll','FxStudio.Automation.dll','FxStudio.Agent.exe'):
        if not (a.published_app/name).is_file():raise ValueError('Provide the merged desktop/Agent publish directory: '+name)
    verify_emulator_build(ROOT,a.emulator_build)
    loader_artifact_hashes(a.artifacts)
    public_component_sources(ROOT,verify=True)
    profile_files={}
    if a.profile_studio:
        profile_manifest=json.loads(source_file(a.profile_studio,'package-manifest.json').read_text('utf-8-sig'))
        if profile_manifest.get('edition') != 'fxstudio-standard':
            raise ValueError('Build the SDK edition with tooling/package_profile_studio.py')
        profile_files=profile_manifest['files']
        for relative,expected in profile_files.items():
            if digest(source_file(a.profile_studio,relative))!=expected:raise ValueError('Profile Studio differs: '+relative)
    out.mkdir(parents=True)
    # Keep the package independent: editing either installation cannot change
    # the other's SDK files. Replacements below still publish atomically.
    for record in manifest['files']:
        if not inherited_file(record['path']):continue
        source=base/record['path'];dest=out/record['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
    for source in a.published_app.rglob('*'):
        if source.is_file():replace(source,out/source.relative_to(a.published_app))
    copy_loader_runtime(ROOT,a.artifacts,out)
    copy_development_runtime(ROOT,out)
    for folder in ('docs','skills','scaffolds'):
        shutil.copytree(ROOT/folder,out/folder,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc','.fxstudio','build*'))
    replace(ROOT/'tooling/engineering.py',out/'automation/engineering.py')
    replace(ROOT/'README.md',out/'README.md')
    replace(ROOT/'README.txt',out/'README.txt')
    (out/'START-HERE.txt').write_text(
        'Fx Studio current development assembly - Windows x64\n\nRun FxStudio.exe.\n'
        'Tools: migrate an fxlib project, import resources, or prepare Loader folders.\n'
        'Read README.md and docs/MIGRATION-AND-RESOURCES.zh-CN.md for current features.\n'
        'Validation scope: docs/VALIDATION-COMPAT-20261118.md and docs/loader/VALIDATION-0.2.md.\n'
        'Read CURRENT-SOURCE-NOTICE.txt before using inherited sources/ or validation/ records.\n', encoding='utf-8')
    copy_verified_emulator(ROOT,a.emulator_build,out/'runtime/emulator')
    if a.profile_studio:
        for relative in (*profile_files,'package-manifest.json'):
            replace(a.profile_studio/relative,out/'ProfileStudio'/relative)
    notes=out/'Loader套件说明.txt'
    notes.write_text('启动 FxStudio.exe。工具 → 为 Loader 准备 G1A；帮助 → 计算器资料。\n'
        '输出目录中的 calculator 文件夹才是计算器安装文件。其余为电脑端报告和 profile。\n'
        '默认只生成程序目录，可选附带或单独导出 Loader。保留 FXAPPS 层级。\n'
        'program-ready 表示依赖就绪，candidate 另含启动器；两者仍需实机验收。\n'
        '普通 G1A 上限 2 MiB。FlashLd 加载普通目录，KLoad 对应已适配的 KhiCAS 版本。\n'
        '超限源码示例与独立使用说明见 sdk/examples/oversized-loader/README.zh-CN.md。\n'
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
             for x in sorted(out.rglob('*')) if x.is_file() and x!=out/'package-manifest.json']
    temporary=out/'package-manifest.suite-new'
    temporary.write_text(json.dumps({'schemaVersion':1,'name':out.name,'basePackage':base.name,'loaderSuiteVersion':'0.2','files':records},indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,out/'package-manifest.json')
    print(json.dumps({'package':str(out),'files':len(records)},ensure_ascii=False))

if __name__=='__main__':main()
