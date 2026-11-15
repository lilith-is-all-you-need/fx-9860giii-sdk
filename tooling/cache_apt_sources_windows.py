"""Cache matching source packages for the Windows-prefetched APT binary superset.

This never starts WSL and does not claim the not-yet-provisioned rootfs is ready.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
from collect_distro_sources import OUT, META, fetch_index, fetch_file

ROOT = Path(__file__).resolve().parents[1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    binary_path = ROOT / 'sdk/downloads/offline-cache-manifest.json'
    binary = json.loads(binary_path.read_text())
    wanted = {(p['source'], p['sourceVersion']) for p in binary['files']}
    queries = [(s, c) for s in ('noble', 'noble-updates', 'noble-security')
               for c in ('main', 'universe')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        indexes = [r for group in pool.map(fetch_index, queries) for r in group]
    lookup = {(r['Package'], r['Version']): r for r in indexes}
    missing = [{'source': s, 'version': v} for s, v in sorted(wanted) if (s, v) not in lookup]
    files = {}
    for key in wanted:
        if key not in lookup:
            continue
        record = lookup[key]
        for line in record['Checksums-Sha256'].splitlines():
            if not line.strip():
                continue
            checksum, size, name = line.split()
            files[name] = (record['Directory'] + '/' + name, checksum, size)
    print(f'Caching {len(files)} source files for {len(wanted)} source packages', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = list(pool.map(fetch_file, files.values()))
    result = {
        'status': 'downloaded corresponding source for cached binary superset; rootfs not yet provisioned',
        'binaryCacheSha256': hashlib.sha256(binary_path.read_bytes()).hexdigest(),
        'packages': [{'source': s, 'version': v} for s, v in sorted(wanted)],
        'missing': missing, 'files': downloaded,
    }
    (OUT / 'offline-cache-sources.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Cached {len(downloaded)} source files; missing versions: {missing}', flush=True)
    if missing:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
