from pathlib import Path
import hashlib
import json
import tarfile
import urllib.request

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'dist-toolchain/native-gdb'
SOURCE=HERE/'source'
URL='https://ftp.gnu.org/gnu/gdb/gdb-16.3.tar.xz'

OUT.mkdir(parents=True,exist_ok=True)
SOURCE.mkdir(parents=True,exist_ok=True)
archive=OUT/'gdb-16.3.tar.xz'
if not archive.exists():
    with urllib.request.urlopen(URL,timeout=120) as src,archive.with_suffix('.part').open('wb') as dst:
        while chunk:=src.read(1024*1024):dst.write(chunk)
    archive.with_suffix('.part').replace(archive)
if not (SOURCE/'gdb-16.3/configure').is_file():
    with tarfile.open(archive) as tar:tar.extractall(SOURCE,filter='data')
with archive.open('rb') as src:digest=hashlib.file_digest(src,'sha256').hexdigest()
(OUT/'source-manifest.json').write_text(json.dumps({'url':URL,'file':archive.name,'bytes':archive.stat().st_size,'sha256':digest},indent=2)+'\n')
print(archive.name,archive.stat().st_size,digest)
