"""Import clean, pinned component source manifests into the offline SDK.

LargeRuntime remains a self-contained CMake/source project under sdk/fxlarge;
its probe projects are also mirrored at the historical SDK probe locations.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def normalized(path):
    data=path.read_bytes()
    return data if path.suffix=='.png' else data.replace(b'\r\n',b'\n')

def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True,encoding='utf-8').strip()

def sync(repositories):
    old=json.loads((ROOT/'loader-components.lock.json').read_text('utf-8'))
    changes={};components=[]
    for component in old['components']:
        name=component['name'];repo=repositories.get(name)
        if repo is None:
            components.append(component)
            for rel,sha in component['files'].items():
                if hashlib.sha256(normalized(ROOT/rel)).hexdigest()!=sha:raise ValueError('Existing snapshot changed: '+rel)
            continue
        repo=Path(repo).resolve()
        if git(repo,'status','--porcelain'):raise ValueError('Commit component changes before syncing: '+name)
        manifest=json.loads((repo/'source-manifest.json').read_text('utf-8'))
        files={};source_paths={}
        for rel,expected in manifest['files'].items():
            source=(repo/rel).resolve()
            if not source.is_relative_to(repo):raise ValueError('Source path escapes repository')
            data=normalized(source)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Component manifest differs: '+rel)
            targets=[rel]
            if name=='fx9860-large-loader':
                targets=['sdk/fxlarge/'+rel]
                if rel.startswith(('probes/','profiles/')):targets.append(rel)
            for target in targets:
                path=(ROOT/target).resolve()
                if not path.is_relative_to(ROOT):raise ValueError('Snapshot escapes SDK')
                if target in changes and changes[target]!=data:raise ValueError('Conflicting shared source: '+target)
                changes[target]=data;files[target]=expected;source_paths[target]=rel
        if name=='fx9860-large-loader':
            target='sdk/fxlarge/source-manifest.json';data=normalized(repo/'source-manifest.json')
            changes[target]=data;files[target]=hashlib.sha256(data).hexdigest();source_paths[target]='source-manifest.json'
        components.append({'name':name,'repository':component['repository'],'commit':git(repo,'rev-parse','HEAD'),
                           'files':dict(sorted(files.items())),'sourcePaths':source_paths})
    # Check every overlap before modifying any files.
    expected_all={}
    for c in components:
        for rel,sha in c['files'].items():
            if rel in expected_all and expected_all[rel]!=sha:raise ValueError('Conflicting snapshots: '+rel)
            expected_all[rel]=sha
    old_all={rel:sha for c in old['components'] for rel,sha in c['files'].items()}
    for rel,sha in old_all.items():
        path=(ROOT/rel).resolve()
        if not path.is_relative_to(ROOT):raise ValueError('Old snapshot path escapes SDK')
        if path.exists() and hashlib.sha256(normalized(path)).hexdigest()!=sha:
            raise ValueError('Local snapshot edit would be overwritten: '+rel)
    for rel,data in changes.items():
        target=ROOT/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for rel in old_all.keys()-expected_all.keys():
        target=(ROOT/rel).resolve()
        if not target.is_relative_to(ROOT):raise ValueError('Removal escapes SDK')
        if target.is_file():target.unlink()
    old['components']=components
    (ROOT/'loader-components.lock.json').write_text(json.dumps(old,indent=2)+'\n',encoding='utf-8')
    return {'components':len(components),'files':len(expected_all)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--loader',type=Path);p.add_argument('--large-loader',type=Path);p.add_argument('--emulator',type=Path)
    a=p.parse_args();args={k:v for k,v in [('fx9860-loader',a.loader),('fx9860-large-loader',a.large_loader),('fx9860-emulator',a.emulator)] if v}
    if not args:p.error('Provide at least one component checkout')
    print(json.dumps(sync(args)))
