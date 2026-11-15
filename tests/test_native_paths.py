"""Regression: Windows short-name aliases must not permit recursive staging."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='FxStudio-path-') as temporary:
    root = Path(temporary).resolve()
    source = root / "工程's source"; source.mkdir()
    (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.15)\nproject(pathcheck C)\n', encoding='utf8')
    output = root / "产物's output"; output.mkdir()
    for cache in (source / 'cache', output / 'cache'):
        env = dict(os.environ, FXIDE_NATIVE_WORK=str(cache), PYTHONUTF8='1')
        result = subprocess.run([sys.executable, str(ROOT/'tooling/build-native.py'), str(sdk), str(source), str(output), 'Debug'],
                                env=env, capture_output=True, encoding='utf8', timeout=15)
        assert result.returncode != 0, result.stdout
        assert ('Native build cache must be outside' in result.stderr or 'needs an ASCII path' in result.stderr), result.stderr
        assert not list(cache.rglob('.fxide-managed')), 'A rejected alias still started source staging'
    assert root.parent == Path(tempfile.gettempdir()).resolve()
print('PASS: source/output short-name aliases cannot contain the native staging cache')
