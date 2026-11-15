"""Verify the offline source snapshots against the published component lock."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    data=path.read_bytes()
    if path.suffix!='.png':data=data.replace(b'\r\n',b'\n')
    return hashlib.sha256(data).hexdigest()

def main():
    lock=json.loads((ROOT/'loader-components.lock.json').read_text(encoding='utf-8'))
    checked=0;seen={}
    for component in lock['components']:
        if len(component['commit'])!=40 or any(c not in '0123456789abcdef' for c in component['commit']):raise ValueError('Unpinned component')
        for relative,expected in component['files'].items():
            path=(ROOT/relative).resolve()
            if not path.is_relative_to(ROOT) or digest(path)!=expected:raise ValueError('Snapshot differs: '+relative)
            if relative in seen and seen[relative]!=expected:raise ValueError('Conflicting shared source: '+relative)
            seen[relative]=expected;checked+=1
    print(json.dumps({'components':len(lock['components']),'fileChecks':checked,'passed':True}))

if __name__=='__main__':main()
