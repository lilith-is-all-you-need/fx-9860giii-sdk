"""Build the standalone skill add-on; the SDK stays in the offline runtime ZIP."""
from pathlib import Path
import argparse
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('SKILL.md', 'agents/openai.yaml', 'scripts/fxstudio.py', 'references/quickstart.zh-CN.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in (*FILES, 'LICENSE'):
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
