"""Fetch or verify the four pinned upstream editor inputs. Offline cache supported."""
import argparse
import hashlib
from pathlib import Path
import shutil
import urllib.request
import zipfile

INPUTS = {
    "wscite569.zip": ("https://www.scintilla.org/wscite569.zip", "68dabc521837f548298d584831c81b0fa5cddc7c21c2ef253f5b3cc56289a747"),
    "scite569.zip": ("https://www.scintilla.org/scite569.zip", "846b1b75ba5a1586dc1c22e869368490df4e6c2beaed36c4097eea1d8b5bbb81"),
    "json.hpp": ("https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp", "9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6"),
    "json.LICENSE": ("https://raw.githubusercontent.com/nlohmann/json/v3.11.3/LICENSE.MIT", "86b998c792894ccb911a1cb7994f7a9652894e7a094c0b5e45be2f553f45cf14"),
}

def prepare(cache):
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in INPUTS.items():
        file = cache / name
        if not file.is_file():
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Upstream digest mismatch: " + name)
            file.write_bytes(data)
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError("Cached dependency digest mismatch: " + name)
    members = {
        "scite569.zip": {"scintilla/include/Scintilla.h": "Scintilla.h", "scintilla/include/Sci_Position.h": "Sci_Position.h",
                         "lexilla/include/SciLexer.h": "SciLexer.h", "scintilla/License.txt": "Scintilla.License.txt",
                         "lexilla/License.txt": "Lexilla.License.txt"},
        "wscite569.zip": {"wscite/Scintilla.dll": "Scintilla.dll", "wscite/Lexilla.dll": "Lexilla.dll"},
    }
    for archive, files in members.items():
        with zipfile.ZipFile(cache / archive) as reader:
            for name, dest in files.items():
                with reader.open(name) as source, (cache / dest).open("wb") as target:
                    shutil.copyfileobj(source, target)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    prepare(parser.parse_args().cache)
