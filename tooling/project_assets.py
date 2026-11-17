"""Offline, non-destructive resource import for ordinary fxSDK CMake projects.

The managed directory is assets/fxstudio; user files are never replaced. The
generated CMake fragment is included at the end of the root CMakeLists.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ASSET_DIR = 'assets/fxstudio'
HEADER = ASSET_DIR + '/project_assets.h'
MANIFEST = ASSET_DIR + '/manifest.json'
FRAGMENT = 'cmake/fxstudio-assets.cmake'
BLOCK = '# BEGIN FXSTUDIO MANAGED ASSETS\ninclude("${CMAKE_CURRENT_SOURCE_DIR}/cmake/fxstudio-assets.cmake")\n# END FXSTUDIO MANAGED ASSETS'
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')
TARGET = re.compile(r'[A-Za-z_][A-Za-z0-9_.+-]*\Z')
CHARSETS = {'numeric': 10, 'upper': 26, 'alpha': 52, 'alnum': 62,
            'print': 95, 'ascii': 128, '256chars': 256}
KEYWORDS = set('alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast requires restrict return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq typeof'.split())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def is_link(path):
    return path.is_symlink() or (path.exists() and bool(getattr(path.stat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def managed_path(project, relative):
    """Validate manifest/output paths before any read or replacement."""
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Invalid managed path: ' + str(relative))
    part = Path(relative)
    if part.is_absolute() or '..' in part.parts or not part.parts:
        raise ValueError('Managed paths must stay inside the project')
    path = project / part
    for ancestor in [path, *path.parents]:
        if ancestor == project:
            break
        if is_link(ancestor):
            raise ValueError('Symbolic links/junctions are not managed: ' + str(ancestor))
    if not path.resolve().is_relative_to(project):
        raise ValueError('Managed path escapes project')
    return path


def cmake_commands(text):
    """Read commands without mistaking quoted text or comments for commands."""
    token = re.compile(r'\s+|\#\[(=*)\[.*?\]\1\]|\#[^\n]*|"(?:\\.|[^"\\])*"|\[(=*)\[.*?\]\2\]|[()]|[^\s()"#]+', re.S)
    tokens = []
    for match in token.finditer(text):
        value = match.group()
        if value.isspace() or value.startswith('#'):
            continue
        if value.startswith('"'):
            value = value[1:-1]
        tokens.append(value)
    i = 0
    while i + 1 < len(tokens):
        if tokens[i + 1] != '(':
            i += 1
            continue
        name, depth, args = tokens[i].lower(), 1, []
        i += 2
        while i < len(tokens) and depth:
            t = tokens[i]
            depth += (t == '(') - (t == ')')
            if depth:
                args.append(t)
            i += 1
        if depth:
            raise ValueError('Unbalanced CMake command; repair CMakeLists.txt first')
        yield name, args


def project_targets(project):
    """Find literal executable targets in the root and explicit subdirectories."""
    found, visited = [], set()

    def condition(args):
        if len(args) == 2 and args[0].upper() == 'NOT':
            value = condition(args[1:])
            return None if value is None else not value
        if not args:
            return False
        if len(args) != 1:
            return None
        value = args[0].upper()
        if value in ('', '0', 'OFF', 'NO', 'FALSE', 'N', 'IGNORE', 'NOTFOUND') or value.endswith('-NOTFOUND'):
            return False
        if value in ('1', 'ON', 'YES', 'TRUE', 'Y'):
            return True
        if re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]*)?', value):
            return float(value) != 0
        return None

    def conjunction(a, b):
        return False if a is False or b is False else None if a is None or b is None else True

    def disjunction(a, b):
        return True if a is True or b is True else None if a is None or b is None else False

    def visit(folder, inherited_name=''):
        file = folder / 'CMakeLists.txt'
        if not file.exists() or file in visited:
            return
        if not folder.resolve().is_relative_to(project):
            return
        managed_path(project, file.relative_to(project).as_posix())
        visited.add(file)
        project_name = inherited_name
        active, branches, dynamic_blocks = True, [], []
        for command, args in cmake_commands(file.read_text('utf-8-sig')):
            if command in ('function', 'macro', 'foreach', 'while'):
                dynamic_blocks.append(command)
                continue
            if command in ('endfunction', 'endmacro', 'endforeach', 'endwhile'):
                if not dynamic_blocks or command != 'end' + dynamic_blocks.pop():
                    raise ValueError('Unbalanced CMake function/loop')
                continue
            if command == 'if':
                value = condition(args)
                branches.append([active, value])
                active = conjunction(active, value)
                continue
            if command in ('else', 'elseif'):
                if not branches:
                    raise ValueError('Unbalanced CMake conditional')
                parent, taken = branches[-1]
                remaining = None if taken is None else not taken
                value = True if command == 'else' else condition(args)
                active = conjunction(parent, conjunction(remaining, value))
                branches[-1][1] = disjunction(taken, value)
                continue
            if command == 'endif':
                if not branches:
                    raise ValueError('Unbalanced CMake conditional')
                active = branches.pop()[0]
                continue
            if active is False:
                continue
            if (active is None or dynamic_blocks) and command in ('add_executable', 'add_subdirectory'):
                raise ValueError('Cannot determine executable targets inside dynamic CMake conditions without executing the project; use an unconditional literal target declaration for resource import')
            if command == 'project' and args and active is True:
                project_name = args[0]
            if command == 'add_executable' and args:
                name = args[0].replace('${PROJECT_NAME}', project_name)
                if '$' in name:
                    raise ValueError('Cannot determine dynamic CMake target names; use an unconditional literal target declaration for resource import')
                if not any(x.upper() in ('IMPORTED', 'ALIAS') for x in args[1:]) and TARGET.fullmatch(name):
                    found.append(name)
            if command == 'add_subdirectory' and args and not any(c in args[0] for c in '$;'):
                child = (folder / args[0]).resolve()
                if child.is_relative_to(project):
                    visit(child, project_name)
        if branches or dynamic_blocks:
            raise ValueError('Unbalanced CMake conditional')
    visit(project)
    return sorted(set(found))


def load_manifest(project):
    path = managed_path(project, MANIFEST)
    if not path.exists():
        return {'schemaVersion': 1, 'assets': [], 'files': {}, '_manifestHash': None}
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Unsupported or damaged asset manifest')
    data['_manifestHash'] = digest(raw)
    if data.get('schemaVersion') != 1 or not isinstance(data.get('assets'), list) or not isinstance(data.get('files'), dict):
        raise ValueError('Unsupported or damaged asset manifest')
    names = set()
    for item in data['assets']:
        if not isinstance(item, dict) or not IDENTIFIER.fullmatch(str(item.get('symbol', ''))) or item['symbol'] in names:
            raise ValueError('Invalid or duplicate resource symbol in manifest')
        names.add(item['symbol'])
        if not TARGET.fullmatch(str(item.get('target', ''))) or item.get('kind') not in ('bitmap', 'binary', 'image', 'font'):
            raise ValueError('Invalid resource kind/target in manifest')
        expected = f'{ASSET_DIR}/{item["symbol"]}/' + ('data.c' if item['kind'] in ('bitmap', 'binary') else 'source.png')
        if item.get('compiledSource') != expected or expected not in data['files']:
            raise ValueError('Invalid compiled resource path in manifest')
        for field in (('size', 'width', 'height', 'stride') if item['kind'] == 'bitmap' else ('size',) if item['kind'] == 'binary' else ('width', 'height')):
            if type(item.get(field)) is not int or item[field] < 1:
                raise ValueError('Invalid resource dimensions/size in manifest')
    for name, expected in data['files'].items():
        if not (name.startswith(ASSET_DIR + '/') or name == FRAGMENT) or name == MANIFEST:
            raise ValueError('Manifest contains an unmanaged output path')
        file = managed_path(project, name)
        if not file.is_file() or digest(file.read_bytes()) != expected:
            raise ValueError('A managed file was edited or removed; preserve it and resolve the conflict first: ' + name)
    return data


def list_assets(project):
    project = Path(project).resolve()
    if not (project / 'CMakeLists.txt').is_file():
        raise ValueError('Project needs a root CMakeLists.txt')
    data = load_manifest(project)
    return {'project': str(project), 'targets': project_targets(project), 'assets': data['assets'],
            'header': str(project / HEADER) if data['assets'] else None}


def convert_bitmap(data, threshold=128):
    """MSB-first rows, ceil(width/8) bytes; transparent pixels become white."""
    from PIL import Image
    if not 0 <= threshold <= 255:
        raise ValueError('Threshold must be in 0..255')
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 16_000_000:
            raise ValueError('Image exceeds 16 million pixels')
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('Import a single image frame; animated images require explicit frame selection')
        rgba = original.convert('RGBA')
        white = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        luminance = Image.alpha_composite(white, rgba).convert('L')
        width, height = luminance.size
        stride = (width + 7) // 8
        packed = bytearray(stride * height)
        pixels = luminance.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] < threshold:
                    packed[y * stride + x // 8] |= 0x80 >> (x % 8)
        return bytes(packed), width, height, stride


def _image_png(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 16_000_000:
            raise ValueError('Image exceeds 16 million pixels')
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('Animated/multi-frame resources require explicit frame selection')
        image = original.convert('RGBA')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue(), image.width, image.height


def _c_array(symbol, data):
    rows = ['    ' + ', '.join(f'0x{x:02x}' for x in data[i:i + 16]) + ',' for i in range(0, len(data), 16)]
    return ('/* Generated by Fx Studio resource import. */\n#include "project_assets.h"\n'
            + f'const unsigned char {symbol}[{len(data)}] = {{\n' + '\n'.join(rows) + '\n};\n').encode('utf-8')


def _render_header(assets):
    lines = ['/* Generated by Fx Studio. Import resources with project_assets.py. */',
             '#ifndef FXSTUDIO_PROJECT_ASSETS_H', '#define FXSTUDIO_PROJECT_ASSETS_H']
    if any(x['kind'] in ('image', 'font') for x in assets):
        lines += ['#include <gint/display.h>']
    lines += ['#ifdef __cplusplus', 'extern "C" {', '#endif']
    for item in assets:
        name, kind = item['symbol'], item['kind']
        if kind in ('bitmap', 'binary'):
            lines += [f'extern const unsigned char {name}[{item["size"]}];', f'#define {name}_size {item["size"]}u']
            if kind == 'bitmap':
                lines += [f'#define {name}_{field} {item[field]}u' for field in ('width', 'height', 'stride')]
        else:
            lines += [f'extern const {"bopti_image_t" if kind == "image" else "font_t"} {name};']
    lines += ['#ifdef __cplusplus', '}', '#endif', '#endif', '']
    return '\n'.join(lines).encode('utf-8')


def _render_cmake(assets):
    lines = ['# Generated by Fx Studio resource import.', 'set(_fxstudio_asset_root "${CMAKE_CURRENT_LIST_DIR}/../assets/fxstudio")']
    if any(x['kind'] in ('bitmap', 'binary') for x in assets):
        # A normal C++ template enables only CXX; generated arrays are C sources.
        lines.append('enable_language(C)')
    if any(x['kind'] in ('image', 'font') for x in assets):
        lines.append('include(Fxconv)')
    for target in sorted(set(x['target'] for x in assets)):
        lines += [f'if(NOT TARGET {target})', f'  message(FATAL_ERROR "Resource target {target} is not defined before the managed include")', 'endif()',
                  f'target_include_directories({target} PRIVATE "${{_fxstudio_asset_root}}")']
    for item in assets:
        source = item['compiledSource'][len(ASSET_DIR) + 1:]
        path = '${_fxstudio_asset_root}/' + source
        if item['kind'] in ('image', 'font'):
            lines += [f'fxconv_declare_assets("{path}" WITH_METADATA)']
        lines += [f'target_sources({item["target"]} PRIVATE "{path}")']
    lines += ['unset(_fxstudio_asset_root)', '']
    return '\n'.join(lines).encode('utf-8')


def _commit(project, outputs, expected):
    """Validate first, stage bytes, then replace; roll back a partial commit."""
    # Compare with the hashes captured BEFORE conversion, never with a fresh
    # baseline. A concurrent editor change must survive even the first import.
    for name, wanted in expected.items():
        path = managed_path(project, name)
        current = digest(path.read_bytes()) if path.exists() else None
        if current != wanted:
            raise ValueError('File changed during import: ' + name)
    originals = {name: (project / name).read_bytes() if (project / name).exists() else None for name in outputs}
    for name, original in originals.items():
        if (digest(original) if original is not None else None) != expected[name]:
            raise ValueError('File changed during import: ' + name)
    done = []
    with tempfile.TemporaryDirectory(prefix='.fx-assets-', dir=project) as temporary:
        stage = Path(temporary)
        for index, (name, data) in enumerate(outputs.items()):
            (stage / str(index)).write_bytes(data)
        try:
            for index, name in enumerate(outputs):
                path = managed_path(project, name)
                # Recheck the content after staging, before replacing it.
                current = path.read_bytes() if path.exists() else None
                if current != originals[name]:
                    raise ValueError('File changed during import: ' + name)
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / str(index), path)
                done.append(name)
        except Exception:
            for name in reversed(done):
                path = managed_path(project, name)
                # Do not roll back over a second writer's later edit.
                if not path.exists() or path.read_bytes() != outputs[name]:
                    continue
                if originals[name] is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(originals[name])
            raise


def _user_sources(project):
    for folder, directories, names in os.walk(project, followlinks=False):
        folder = Path(folder)
        directories[:] = [name for name in directories if not name.startswith('build')
                          and name not in ('.git', '.fxstudio', '.vs', 'compat', 'node_modules')
                          and not is_link(folder / name)
                          and (folder / name).relative_to(project).as_posix() != ASSET_DIR]
        for name in names:
            path = folder / name
            if path.suffix.lower() in ('.c', '.h', '.cpp', '.hpp') and not is_link(path):
                yield path


def _defines_symbol(text, symbols):
    # Strings/comments can contain arbitrary example code; preserve newlines
    # while replacing their contents before looking for declarations.
    code = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), text, flags=re.S)
    alternatives = '(?:' + '|'.join(re.escape(x) for x in symbols) + ')'
    if re.search(r'(?m)^\s*#\s*define\s+' + alternatives + r'\b', code):
        return True
    code = re.sub(r'(?m)^\s*#[^\n]*(?:\\\n[^\n]*)*', '', code)
    for match in re.finditer(r'\b' + alternatives + r'\b', code):
        start = max(code.rfind(delimiter, 0, match.start()) for delimiter in ';{}') + 1
        prefix = code[start:match.start()].strip()
        # Accept a type/qualifier sequence (including typedef names), not an
        # expression such as return blob[1] == value or draw(..., &blob).
        if not prefix or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_\s:*&<>]*', prefix):
            continue
        words = re.findall(r'[A-Za-z_]\w*', prefix)
        if words[0] in ('return', 'goto', 'case', 'throw', 'delete', 'sizeof', 'alignof', 'co_return', 'co_yield'):
            continue
        suffix = code[match.end():]
        dimensions = re.match(r'\s*(?:\[[^\];]*\]\s*)*', suffix).end()
        tail = suffix[dimensions:].lstrip()
        if tail.startswith('('):  # A function/prototype shares the C namespace.
            return True
        initializer = tail.startswith('=') and not tail.startswith('==')
        if ('extern' not in words or initializer) and (initializer or tail.startswith((';', ','))):
            return True
    return False


def import_asset(project, input, kind='bitmap', symbol=None, target=None, dry_run=False,
                 threshold=128, font_grid=None, font_charset='numeric'):
    project, input = Path(project).resolve(), Path(input).resolve()
    cmake = managed_path(project, 'CMakeLists.txt')
    if not cmake.is_file() or not input.is_file():
        raise ValueError('A CMake project and an existing input file are required')
    if not symbol or not IDENTIFIER.fullmatch(symbol) or symbol in KEYWORDS:
        raise ValueError('Use a C identifier beginning with a letter, not a keyword')
    if kind not in ('bitmap', 'image', 'binary', 'font'):
        raise ValueError('Unknown asset kind')
    targets = project_targets(project)
    if target is None:
        if len(targets) != 1:
            raise ValueError('Select --target explicitly; executable targets: ' + ', '.join(targets))
        target = targets[0]
    if target not in targets:
        raise ValueError('Target must be a declared executable: ' + ', '.join(targets))
    if input.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Input is larger than 64 MiB')
    raw = input.read_bytes()
    if not raw:
        raise ValueError('Empty resources are not supported')
    data = load_manifest(project)
    cmake_raw = cmake.read_bytes()
    initial = {'CMakeLists.txt': digest(cmake_raw), MANIFEST: data['_manifestHash'], **data['files']}
    cmake_text = cmake_raw.decode('utf-8-sig').replace('\r\n', '\n')
    marker_count = cmake_text.count('# BEGIN FXSTUDIO MANAGED ASSETS')
    if data['assets']:
        if marker_count != 1 or cmake_text.count(BLOCK) != 1:
            raise ValueError('Managed CMake include was changed; resolve it before importing')
    elif marker_count or 'fxstudio-assets.cmake' in cmake_text:
        raise ValueError('An unmanaged resource include already exists')
    options = {'threshold': threshold} if kind == 'bitmap' else ({'fontGrid': font_grid, 'fontCharset': font_charset} if kind == 'font' else {})
    identity = {'symbol': symbol, 'kind': kind, 'target': target, 'inputSha256': digest(raw), 'options': options}
    for previous in data['assets']:
        if previous['symbol'] == symbol:
            if all(previous.get(key) == value for key, value in identity.items()):
                return {'project': str(project), 'target': target, 'symbol': symbol, 'unchanged': True,
                        'header': str(project / HEADER), 'files': [], 'warnings': [], 'dryRun': dry_run}
            raise ValueError('Symbol already imported with different data/options: ' + symbol)
        if symbol in {previous['symbol'] + suffix for suffix in ('_size', '_width', '_height', '_stride')} or previous['symbol'] in {symbol + suffix for suffix in ('_size', '_width', '_height', '_stride')}:
            raise ValueError('Symbol conflicts with another resource dimension/size name')
    # Reject actual user definitions, while allowing pre-existing references.
    symbols = [symbol] + ([symbol + '_size'] if kind in ('bitmap', 'binary') else []) + ([symbol + suffix for suffix in ('_width', '_height', '_stride')] if kind == 'bitmap' else [])
    for source in _user_sources(project):
        relative = source.relative_to(project).as_posix()
        if _defines_symbol(source.read_text('utf-8-sig', errors='replace'), symbols):
            raise ValueError('Symbol already defined by a project source: ' + relative)
    folder = f'{ASSET_DIR}/{symbol}'
    if managed_path(project, folder).exists():
        raise ValueError('Resource destination already exists and is not managed: ' + folder)
    outputs, item, warnings = {}, dict(identity), []
    if kind in ('bitmap', 'binary'):
        if kind == 'bitmap':
            packed, width, height, stride = convert_bitmap(raw, threshold)
            item.update(width=width, height=height, stride=stride)
            image, _, _ = _image_png(raw)
            outputs[folder + '/source.png'] = image
            warnings.append('Bitmap: MSB-first, byte-padded rows; transparency is composited on white.')
        else:
            packed = raw
            outputs[folder + '/source.bin'] = raw
        item.update(size=len(packed), compiledSource=folder + '/data.c')
        outputs[item['compiledSource']] = _c_array(symbol, packed)
    else:
        png, width, height = _image_png(raw)
        item.update(width=width, height=height, compiledSource=folder + '/source.png')
        outputs[item['compiledSource']] = png
        metadata = f'source.png:\n  type: {"bopti-image" if kind == "image" else "font"}\n  name: {symbol}\n'
        if kind == 'image':
            metadata += '  profile: mono_alpha\n'
        else:
            match = re.fullmatch(r'([1-9][0-9]*)x([1-9][0-9]*)', font_grid or '')
            if not match or font_charset not in CHARSETS:
                raise ValueError('Font needs --font-grid WxH and a supported --font-charset')
            w, h = map(int, match.groups())
            if w > 255 or h > 255 or width % w or height % h or (width // w) * (height // h) < CHARSETS[font_charset]:
                raise ValueError('Font sheet must be an exact grid with enough glyphs; cells are at most 255x255')
            metadata += f'  charset: {font_charset}\n  grid.size: {font_grid}\n  proportional: false\n  char-spacing: 1\n'
        outputs[folder + '/fxconv-metadata.txt'] = metadata.encode('utf-8')
        warnings.append('Converted by fxconv during the next build; import does not prove final rendering.')
    assets = [*data['assets'], item]
    outputs[HEADER] = _render_header(assets)
    outputs[FRAGMENT] = _render_cmake(assets)
    for name in outputs:
        if managed_path(project, name).exists() and name not in data['files']:
            raise ValueError('Refusing to replace a user file: ' + name)
    hashes = dict(data['files'])
    hashes.update({name: digest(content) for name, content in outputs.items()})
    outputs[MANIFEST] = (json.dumps({'schemaVersion': 1, 'assets': assets, 'files': hashes}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if not data['assets']:
        newline = b'\r\n' if b'\r\n' in cmake_raw else b'\n'
        outputs['CMakeLists.txt'] = cmake_raw + newline + BLOCK.replace('\n', newline.decode()).encode('utf-8') + newline
    result = {'project': str(project), 'target': target, 'symbol': symbol, 'kind': kind, 'unchanged': False,
              'header': str(project / HEADER), 'files': list(outputs), 'warnings': warnings, 'dryRun': dry_run,
              'report': 'Resource prepared. Include <project_assets.h> and build the selected target.'}
    if not dry_run:
        expected = {name: initial.get(name) for name in outputs}
        expected['CMakeLists.txt'] = initial['CMakeLists.txt']
        _commit(project, outputs, expected)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--project', required=True, type=Path)
    importer = sub.add_parser('import')
    importer.add_argument('--project', required=True, type=Path)
    importer.add_argument('--input', required=True, type=Path)
    importer.add_argument('--kind', choices=['bitmap', 'image', 'binary', 'font'], default='bitmap')
    importer.add_argument('--symbol', required=True)
    importer.add_argument('--target')
    importer.add_argument('--dry-run', action='store_true')
    importer.add_argument('--threshold', type=int, default=128)
    importer.add_argument('--font-grid')
    importer.add_argument('--font-charset', choices=list(CHARSETS), default='numeric')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = list_assets(**args) if command == 'list' else import_asset(**args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
