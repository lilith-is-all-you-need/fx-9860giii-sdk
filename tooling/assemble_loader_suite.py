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
    p.add_argument('--profile-studio',type=Path,help='Complete separately verified Profile Studio portable directory')
    a=p.parse_args();base=a.base_package.resolve();out=a.destination.resolve()
    if out.exists() or out.is_relative_to(base):raise ValueError('Choose a new folder outside the base package')
    for rel in ('FxStudio.Agent.exe','sdk/native/host/python/python.exe','package-manifest.json'):
        if not (base/rel).is_file():raise ValueError('Incomplete base SDK: '+rel)
    manifest=json.loads((base/'package-manifest.json').read_text(encoding='utf-8-sig'))
    for record in manifest['files']:
        source=(base/record['path']).resolve()
        if not source.is_relative_to(base) or digest(source)!=record['sha256']:raise ValueError('Base package differs: '+record['path'])
    artifacts=json.loads((a.artifacts/'manifest.json').read_text('utf-8'))
    if artifacts.get('bundleFormat')!=2:raise ValueError('Folder Loader artifacts are required')
    for name,expected in artifacts['files'].items():
        if Path(name).name!=name or digest(a.artifacts/name)!=expected:raise ValueError('Invalid Loader artifact: '+name)
    if not {'FlashLd.g1a','KLoad.g1a','ExtLoad.g1a'}<=artifacts['files'].keys():raise ValueError('Incomplete Loader set')
    profile_files={}
    if a.profile_studio:
        profile_files=json.loads((a.profile_studio/'package-manifest.json').read_text('utf-8'))['files']
        for relative,expected in profile_files.items():
            src=(a.profile_studio/relative).resolve()
            if not src.is_relative_to(a.profile_studio.resolve()) or digest(src)!=expected:raise ValueError('Profile Studio differs: '+relative)
    lock=json.loads((ROOT/'loader-components.lock.json').read_text('utf-8'))
    component_files={rel:sha for c in lock['components'] for rel,sha in c['files'].items()}
    for rel,expected in component_files.items():
        src=(ROOT/rel).resolve()
        raw=src.read_bytes() if src.is_relative_to(ROOT) else b''
        if src.suffix!='.png':raw=raw.replace(b'\r\n',b'\n')
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Component differs: '+rel)
    out.mkdir(parents=True)
    # Keep the package independent: editing either installation cannot change
    # the other's SDK files. Replacements below still publish atomically.
    for record in manifest['files']:
        source=base/record['path'];dest=out/record['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
    for source in a.published_app.rglob('*'):
        if source.is_file():replace(source,out/source.relative_to(a.published_app))
    for rel in (*component_files,'loader-components.lock.json','README.md'):
        replace(ROOT/rel,out/rel)
    for source in (ROOT/'docs').rglob('*'):
        if source.is_file():replace(source,out/source.relative_to(ROOT))
    for name in (*artifacts['files'],'manifest.json'):
        replace(a.artifacts/name,out/'loader-artifacts'/name)
    if a.profile_studio:
        for relative in (*profile_files,'package-manifest.json'):
            replace(a.profile_studio/relative,out/'ProfileStudio'/relative)
    notes=out/'Loader套件说明.txt'
    notes.write_text('启动 FxStudio.exe。工具 → 为 Loader 准备 G1A；帮助 → 计算器资料。\n'
        '输出目录中的 calculator 文件夹才是计算器安装文件。其余为电脑端报告和 profile。\n'
        '默认只生成程序目录，可选附带或单独导出 Loader。保留 FXAPPS 层级。\n'
        'program-ready 表示依赖就绪，candidate 另含启动器；两者仍需实机验收。\n'
        '普通程序使用 FlashLd；原版 KhiCAS 使用 KLoad；源码接入的动态超限程序使用 ExtLoad。\n'
        '调用者会话库尚缺通用 Flash 返回后端；未知超限二进制不因 Ghidra 完成而自动支持。\n'
        '本目录是独立的新版本，原安装包保留。\n',encoding='utf-8-sig')
    records=[{'path':x.relative_to(out).as_posix(),'bytes':x.stat().st_size,'sha256':digest(x)}
             for x in sorted(out.rglob('*')) if x.is_file() and x!=out/'package-manifest.json']
    temporary=out/'package-manifest.suite-new'
    temporary.write_text(json.dumps({'schemaVersion':1,'name':out.name,'basePackage':base.name,'loaderSuiteVersion':'0.2','files':records},indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,out/'package-manifest.json')
    print(json.dumps({'package':str(out),'files':len(records)},ensure_ascii=False))

if __name__=='__main__':main()
