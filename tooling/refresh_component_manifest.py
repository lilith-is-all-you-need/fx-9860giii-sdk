"""Refresh an explicit authored-source manifest before committing a component."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SUFFIXES={'.c','.h','.cpp','.hpp','.S','.ld','.cmake','.py','.ps1','.md','.json','.png','.patch','.txt','.cs','.xaml','.csproj','.manifest','.java','.xml'}
IGNORED={'.fxstudio','__pycache__','evidence','graphics-audit','bin','obj','.vs','build'}

def refresh(repo,kind):
    repo=Path(repo).resolve()
    names=subprocess.check_output(['git','-C',str(repo),'-c','core.quotepath=false','ls-files','--cached','--others','--exclude-standard','-z']).decode('utf-8').split('\0')
    files={}
    for name in sorted(set(names)):
        if not name or name=='source-manifest.json':continue
        path=repo/name;parts=Path(name).parts
        if not path.is_file() or IGNORED.intersection(parts) or any(p.startswith('build-') for p in parts):continue
        if path.suffix not in SUFFIXES and path.name not in ('CMakeLists.txt','LICENSE'):continue
        if kind=='loader':
            allowed=name.startswith(('probes/native-loader/','probes/storage-loader/','profiles/','desktop/ProfileStudio/','tooling/','tests/','sdk/caller-session/')) or name=='probes/mapped-loader/tools/prepare.py'
        else:
            allowed=name.startswith(('probes/','profiles/','docs/','include/','src/','tests/','tooling/')) or name in ('CMakeLists.txt','README.md','LICENSE','VALIDATION-DYNAMIC-20261118.json')
        if not allowed:continue
        data=path.read_bytes()
        if path.suffix!='.png':data=data.replace(b'\r\n',b'\n')
        files[name]=hashlib.sha256(data).hexdigest()
    (repo/'source-manifest.json').write_text(json.dumps({'schemaVersion':1,'component':kind,'files':files},indent=2)+'\n',encoding='utf-8')
    return len(files)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('repo',type=Path);p.add_argument('--kind',choices=['loader','large-loader'],required=True)
    a=p.parse_args();print(json.dumps({'files':refresh(a.repo,a.kind)}))
