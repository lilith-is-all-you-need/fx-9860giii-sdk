"""Transfer existing ZIPs without re-uploading public, hash-pinned source archives.

This preserves original ZIP headers, compressed bytes, and directory records.
It does not rebuild or recompress any release. All reconstructed output hashes
must equal the already validated local ZIP hashes before publication.
"""
from pathlib import Path
import argparse, concurrent.futures, hashlib, json, re, shutil, struct, urllib.request, zipfile

CHUNK = 8 * 1024 * 1024

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def checked_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value) or value in ('.', '..'):
        raise ValueError('Unsafe artifact name')
    return value

def checked_hash(value):
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid SHA-256')
    return value

def data_offset(path, member):
    with path.open('rb') as f:
        f.seek(member.header_offset)
        header = f.read(30)
    if header[:4] != b'PK\x03\x04':
        raise ValueError('Invalid local ZIP header')
    name_length, extra_length = struct.unpack('<HH', header[26:30])
    return member.header_offset + 30 + name_length + extra_length

def copy_range(source, destination, size):
    remaining = size
    while remaining:
        block = source.read(min(CHUNK, remaining))
        if not block:
            raise EOFError('Truncated input')
        destination.write(block)
        remaining -= len(block)

def prepare(root, output, version):
    checked_name(version)
    output.mkdir(parents=True, exist_ok=False)
    cache = output / 'cache'; cache.mkdir()
    source = root / f'dist-windows/FxStudio-{version}-sources.zip'
    runtime = root / f'dist-windows/FxStudio-{version}-win-x64.zip'
    urls = {}
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('url'), str) and isinstance(value.get('sha256'), str):
                urls[value['sha256']] = value['url']
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    cuts = []
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            if member.filename.endswith('.json') and member.file_size < 2_000_000:
                try: walk(json.loads(archive.read(member)))
                except (ValueError, UnicodeError): pass
        for member in archive.infolist():
            if member.compress_type != zipfile.ZIP_STORED or member.file_size < 1_000_000:
                continue
            data = archive.read(member); sha = hashlib.sha256(data).hexdigest()
            if sha not in urls or not urls[sha].startswith('https://') or urls[sha].endswith('.git'):
                continue
            (cache / sha).write_bytes(data)
            cuts.append((data_offset(source, member), len(data),
                         {'kind':'download', 'url':urls[sha], 'sha256':sha, 'bytes':len(data)}))
    source_sha = digest(source)
    with zipfile.ZipFile(runtime) as archive:
        member = archive.getinfo(f'FxStudio-{version}-win-x64/sources/{source.name}')
        if member.compress_type != zipfile.ZIP_STORED or member.file_size != source.stat().st_size:
            raise ValueError('Runtime must store the matching source ZIP without recompression')
        if hashlib.sha256(archive.read(member)).hexdigest() != source_sha:
            raise ValueError('Runtime contains different corresponding sources')
        runtime_cuts = [(data_offset(runtime,member),member.file_size,
                         {'kind':'output', 'file':source.name, 'sha256':source_sha, 'bytes':member.file_size})]
    manifest = {'schemaVersion':1, 'version':version, 'parts':[], 'outputs':[]}
    payload = output / 'payload.bin'
    with payload.open('wb') as packed:
        for path, removed in [(source, cuts), (runtime, runtime_cuts)]:
            record = {'file':path.name, 'bytes':path.stat().st_size, 'sha256':digest(path), 'segments':[]}
            position = 0
            with path.open('rb') as original:
                for offset, size, replacement in sorted(removed, key=lambda x:x[0]):
                    if offset < position: raise ValueError('Overlapping ZIP ranges')
                    if offset > position:
                        record['segments'].append({'kind':'literal','offset':packed.tell(),'bytes':offset-position})
                        original.seek(position); copy_range(original, packed, offset-position)
                    record['segments'].append(replacement)
                    position = offset + size
                if position < record['bytes']:
                    record['segments'].append({'kind':'literal','offset':packed.tell(),'bytes':record['bytes']-position})
                    original.seek(position); copy_range(original, packed, record['bytes']-position)
            manifest['outputs'].append(record)
    manifest['payloadSha256'] = digest(payload)
    with payload.open('rb') as stream:
        index=0
        while data := stream.read(CHUNK):
            name=f'transfer-v{version}-{index:03}.bin'
            (output/name).write_bytes(data)
            manifest['parts'].append({'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            index+=1
    target = output/f'transfer-v{version}-manifest.json'
    target.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'manifest':str(target),'uploadBytes':payload.stat().st_size,
                      'originalBytes':sum(x['bytes'] for x in manifest['outputs']),
                      'parts':len(manifest['parts']),'publicSourceRanges':len(cuts)}),flush=True)

def prepare_delta(root, baseline, output, version):
    """Reuse unchanged compressed ZIP members from already uploaded baselines."""
    checked_name(version)
    output.mkdir(parents=True,exist_ok=False)
    manifest={'schemaVersion':1,'version':version,'parts':[],'outputs':[],'baseAssets':[]}
    source_name=f'FxStudio-{version}-sources.zip'
    names=[source_name,f'FxStudio-{version}-win-x64.zip']
    payload=output/'payload.bin'
    with payload.open('wb') as packed:
        for name in names:
            current=root/'dist-windows'/name; base=baseline/name
            manifest['baseAssets'].append({'file':name,'bytes':base.stat().st_size,'sha256':digest(base)})
            cuts=[]
            with zipfile.ZipFile(current) as new_zip, zipfile.ZipFile(base) as old_zip, current.open('rb') as new_bytes, base.open('rb') as old_bytes:
                old_members={member.filename:member for member in old_zip.infolist()}
                for member in new_zip.infolist():
                    start=data_offset(current,member)
                    if name!=source_name and member.filename.endswith('/sources/'+source_name):
                        source=root/'dist-windows'/source_name
                        if member.compress_type!=zipfile.ZIP_STORED or member.file_size!=source.stat().st_size:
                            raise ValueError('Source companion must be stored without compression')
                        if hashlib.sha256(new_zip.read(member)).hexdigest()!=digest(source):
                            raise ValueError('Embedded source companion mismatch')
                        cuts.append((start,member.compress_size,{'kind':'output','file':source_name,'bytes':member.compress_size,'sha256':digest(source)}))
                        continue
                    old=old_members.get(member.filename)
                    if old is None or old.compress_size!=member.compress_size or member.compress_size<128:
                        continue
                    old_start=data_offset(base,old)
                    new_bytes.seek(start); old_bytes.seek(old_start)
                    remaining=member.compress_size; same=True
                    while remaining:
                        size=min(CHUNK,remaining)
                        if new_bytes.read(size)!=old_bytes.read(size): same=False;break
                        remaining-=size
                    if same:
                        cuts.append((start,member.compress_size,{'kind':'base','file':name,'offset':old_start,'bytes':member.compress_size}))
                record={'file':name,'bytes':current.stat().st_size,'sha256':digest(current),'segments':[]}
                position=0
                for offset,size,replacement in sorted(cuts,key=lambda x:x[0]):
                    if offset<position: raise ValueError('Overlapping ranges')
                    if offset>position:
                        record['segments'].append({'kind':'literal','offset':packed.tell(),'bytes':offset-position})
                        new_bytes.seek(position);copy_range(new_bytes,packed,offset-position)
                    record['segments'].append(replacement);position=offset+size
                if position<record['bytes']:
                    record['segments'].append({'kind':'literal','offset':packed.tell(),'bytes':record['bytes']-position})
                    new_bytes.seek(position);copy_range(new_bytes,packed,record['bytes']-position)
                manifest['outputs'].append(record)
    manifest['payloadSha256']=digest(payload)
    with payload.open('rb') as stream:
        index=0
        while data:=stream.read(CHUNK):
            name=f'transfer-v{version}-{index:03}.bin';(output/name).write_bytes(data)
            manifest['parts'].append({'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()});index+=1
    (output/f'transfer-v{version}-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    # Validate reconstruction without creating another pair of large ZIP copies.
    for record in manifest['outputs']:
        actual=hashlib.sha256()
        for segment in record['segments']:
            kind=segment['kind']
            path=payload if kind=='literal' else baseline/segment['file'] if kind=='base' else root/'dist-windows'/segment['file']
            with path.open('rb') as source:
                source.seek(segment.get('offset',0));remaining=segment['bytes']
                while remaining:
                    data=source.read(min(CHUNK,remaining))
                    if not data:raise EOFError('Truncated reconstruction input')
                    actual.update(data);remaining-=len(data)
        if actual.hexdigest()!=record['sha256']:raise ValueError('Delta failed local reconstruction check')
    print(json.dumps({'deltaBytes':payload.stat().st_size,'parts':len(manifest['parts']),'verifiedOutputs':[x['file'] for x in manifest['outputs']]}),flush=True)

def restore(manifest_path, output, cache, base_directory=None):
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    if manifest['schemaVersion'] != 1: raise ValueError('Unsupported transfer manifest')
    output.mkdir(parents=True,exist_ok=False)
    cache.mkdir(parents=True,exist_ok=True)
    bases={}
    for record in manifest.get('baseAssets',[]):
        if base_directory is None:raise ValueError('Baseline ZIP directory is required')
        path=base_directory/checked_name(record['file'])
        if path.stat().st_size!=record['bytes'] or digest(path)!=checked_hash(record['sha256']):
            raise ValueError('Baseline ZIP does not match the validated original')
        bases[record['file']]=path
    payload = output/'transfer-payload.bin'
    with payload.open('wb') as stream:
        for part in manifest['parts']:
            path=manifest_path.parent/checked_name(part['file'])
            if path.stat().st_size!=part['bytes'] or digest(path)!=checked_hash(part['sha256']):
                raise ValueError('Transfer part failed verification: '+part['file'])
            with path.open('rb') as source: shutil.copyfileobj(source,stream,CHUNK)
    if digest(payload)!=checked_hash(manifest['payloadSha256']): raise ValueError('Payload hash mismatch')
    downloads={}
    for record in manifest['outputs']:
        for segment in record['segments']:
            if segment['kind']=='download': downloads[checked_hash(segment['sha256'])]=segment
    def fetch(item):
        sha, segment=item
        path=cache/sha
        if path.exists() and path.stat().st_size==segment['bytes'] and digest(path)==sha: return
        if not segment['url'].startswith('https://'): raise ValueError('Only HTTPS source downloads are allowed')
        for attempt in range(3):
            try:
                with urllib.request.urlopen(segment['url'],timeout=120) as response, path.open('wb') as target:
                    if not response.geturl().startswith('https://'): raise ValueError('Insecure download redirect')
                    copy_range(response,target,segment['bytes'])
                    if response.read(1): raise ValueError('Source download exceeds recorded length')
                if digest(path)!=sha: raise ValueError('Source download hash mismatch')
                print('Verified upstream source '+sha[:12],flush=True)
                return
            except Exception:
                if attempt==2: raise
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch, downloads.items()))
    complete={}
    for record in manifest['outputs']:
        target=output/checked_name(record['file'])
        if target.name=='transfer-payload.bin': raise ValueError('Reserved filename')
        with target.open('xb') as destination, payload.open('rb') as literal:
            for segment in record['segments']:
                size=segment['bytes']
                if not isinstance(size,int) or size<0: raise ValueError('Invalid segment length')
                if segment['kind']=='literal':
                    offset=segment['offset']
                    if not isinstance(offset,int) or offset<0 or offset+size>payload.stat().st_size:
                        raise ValueError('Invalid payload range')
                    literal.seek(offset); copy_range(literal,destination,size)
                elif segment['kind']=='base':
                    path=bases[checked_name(segment['file'])];offset=segment['offset']
                    if not isinstance(offset,int) or offset<0 or offset+size>path.stat().st_size:
                        raise ValueError('Invalid baseline range')
                    with path.open('rb') as source:
                        source.seek(offset);copy_range(source,destination,size)
                else:
                    if segment['kind']=='download': path=cache/checked_hash(segment['sha256'])
                    elif segment['kind']=='output': path=complete[checked_name(segment['file'])]
                    else: raise ValueError('Unknown segment kind')
                    if path.stat().st_size!=size or digest(path)!=checked_hash(segment['sha256']):
                        raise ValueError('Input segment hash mismatch')
                    with path.open('rb') as source: copy_range(source,destination,size)
        if target.stat().st_size!=record['bytes'] or digest(target)!=checked_hash(record['sha256']):
            raise ValueError('Reconstructed release differs from validated original: '+target.name)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None: raise ValueError('ZIP CRC failed')
        complete[target.name]=target
        print('Verified byte-identical release: '+target.name+' '+record['sha256'],flush=True)
    (output/'verified-release-assets.json').write_text(json.dumps([
        {k:record[k] for k in ('file','bytes','sha256')} for record in manifest['outputs']],indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    make=commands.add_parser('prepare'); make.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); make.add_argument('--output',type=Path,required=True); make.add_argument('--version',default='0.2.0')
    delta=commands.add_parser('prepare-delta'); delta.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); delta.add_argument('--baseline',type=Path,required=True); delta.add_argument('--output',type=Path,required=True); delta.add_argument('--version',default='0.2.0')
    build=commands.add_parser('restore'); build.add_argument('--manifest',type=Path,required=True); build.add_argument('--output',type=Path,required=True); build.add_argument('--cache',type=Path,required=True); build.add_argument('--base-directory',type=Path)
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.root,args.output,args.version)
    elif args.command=='prepare-delta': prepare_delta(args.root,args.baseline,args.output,args.version)
    else: restore(args.manifest,args.output,args.cache,args.base_directory)
