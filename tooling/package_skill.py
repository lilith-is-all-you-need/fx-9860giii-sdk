"""Build the standalone skill add-on; the SDK stays in the offline runtime ZIP."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile
from sync_engineering_skill import sync

ROOT = Path(__file__).resolve().parents[1]
FILES = ('SKILL.md', 'agents/openai.yaml', 'scripts/fxstudio.py', 'scripts/engineering.py',
         'references/quickstart.zh-CN.md', 'references/engineering.zh-CN.md',
         'assets/scaffolds-manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sync(check=True)
    inventory = json.loads((ROOT / 'skills/fxstudio/assets/scaffolds-manifest.json').read_text(encoding='utf8'))
    assets = tuple('assets/scaffolds/' + row['path'] for row in inventory['files'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in (*FILES, *assets, 'LICENSE'):
            path = ROOT / 'LICENSE' if name == 'LICENSE' else ROOT / 'skills/fxstudio' / name
            info = zipfile.ZipInfo('fxstudio/' + name, date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + '.sha256').write_text(
        digest + '  ' + args.output.name + '\n', encoding='ascii')
    print(digest + '  ' + str(args.output))


if __name__ == '__main__':
    main()
