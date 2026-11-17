"""Copy an old fxlib source project into a separate, portable gint project.

No original source is edited. This prepares source compatibility, not binary
library compatibility or a claim that arbitrary Casio programs work unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXTENSIONS = {'.c', '.cpp', '.cc', '.cxx'}
HEADER_EXTENSIONS = {'.h', '.hpp', '.hh', '.hxx', '.inc'}
IGNORED_DIRS = {'.git', '.svn', '.fxstudio', '.vs', '__pycache__', 'debug', 'release', 'init', 'bin', 'obj'}
STARTUP_FILES = {'crt0.c', 'crt0.s', 'crt0.src', 'crt0.cpp', 'fxlib_entry.c', 'addininit.c', 'addinit.c'}
BUILD_EXTENSIONS = {'.o', '.obj', '.a', '.lib', '.elf', '.g1a', '.g3a', '.map', '.lst', '.d', '.pdb', '.exe', '.dll'}
RESOURCE_EXTENSIONS = {'.png', '.bmp', '.jpg', '.jpeg', '.gif', '.tif', '.tiff', '.ico', '.bin', '.dat', '.raw', '.fnt', '.fxconv'}


def _link(path):
    return path.is_symlink() or (path.exists() and bool(getattr(path.stat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def _source_text(raw):
    try:
        return raw.decode('utf-8-sig'), False
    except UnicodeDecodeError:
        return raw.decode('latin-1'), True


def _code_only(text):
    """Keep line numbers while ignoring comments and string literal contents."""
    expression = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(expression, lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), text, flags=re.S)


def _catalog(compat):
    path = compat / 'api.json'
    if path.exists():
        data = json.loads(path.read_text('utf-8-sig'))
        functions = data.get('functions', {})
        if isinstance(functions, dict):
            return functions
    header = (compat / 'fxlib.h').read_text('utf-8-sig')
    return {name: {'status': 'declared', 'notes': 'See compat/fxlib/README.md for supported semantics.'}
            for name in re.findall(r'^\s*#\s*define\s+(\w+)\s+fxlib_\w+', header, re.M)}


def _scan(relative, text, functions):
    warnings = []
    code = _code_only(text)
    for match in re.finditer(r'^\s*#\s*pragma\b[^\n]*', text, re.M):
        warnings.append({'file': relative, 'line': text[:match.start()].count('\n') + 1,
                         'kind': 'shc-pragma', 'message': 'Review SHC pragma; GCC does not preserve its section/interrupt semantics: ' + match.group().strip()})
    for match in re.finditer(r'\b(?:__asm__|__asm|asm)\s*\(|\b0x(?:80010070|a0000000)\b|#\s*pragma\s+inline_asm', code, re.I):
        warnings.append({'file': relative, 'line': code[:match.start()].count('\n') + 1,
                         'kind': 'assembly-or-syscall', 'message': 'Direct assembly, reset or syscall trampoline needs manual ABI/hardware review.'})
    seen = set()
    for match in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', code):
        name = match[1]
        is_os = bool(re.match(r'(?:Bdisp_|Bfile_|Bkey_|Bcd|MCS|RTC_|Serial_|USB_|Timer|SetTimer|KillTimer|GetKey|IsKey|Print|locate$|Sleep$|SetQuit|SaveDisp|RestoreDisp|PopUpWin|GetVRAM|Cursor_|Setup_|Display|GetOS|System_)', name))
        record = functions.get(name)
        if name in seen:
            continue
        seen.add(name)
        if record:
            status = record.get('status', 'declared') if isinstance(record, dict) else str(record)
            if status not in ('supported', 'implemented', 'full'):
                notes = record.get('notes', '') if isinstance(record, dict) else ''
                warnings.append({'file': relative, 'line': code[:match.start()].count('\n') + 1,
                                 'kind': 'api-' + status, 'api': name, 'message': f'{name}: {status}. {notes}'})
        elif is_os:
            warnings.append({'file': relative, 'line': code[:match.start()].count('\n') + 1,
                             'kind': 'unsupported-api', 'api': name, 'message': 'No compatibility declaration found for ' + name})
    return warnings


def _inventory(source):
    single = source.is_file()
    base = source.parent if single else source
    files, skipped, total_bytes = [], [], 0
    for folder, directories, names in os.walk(base, followlinks=False):
        folder = Path(folder)
        retained = []
        for name in sorted(directories):
            child = folder / name
            if name.lower() in IGNORED_DIRS or name.lower().startswith('build') or _link(child):
                skipped.append({'path': child.relative_to(base).as_posix() + '/', 'reason': 'build/startup/cache or linked directory'})
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(names):
            path = folder / name
            relative = path.relative_to(base).as_posix()
            reason = None
            if _link(path):
                reason = 'linked file'
            elif name.lower() in ('fxlib.h', 'dispbios.h', 'keybios.h', 'filebios.h'):
                reason = 'replaced by the independently implemented compatibility header'
            elif name.lower() in STARTUP_FILES:
                reason = 'old startup file; gint supplies startup'
            elif path.suffix.lower() in BUILD_EXTENSIONS:
                reason = 'old compiled artifact/library; cannot be mixed with this GNU build'
            elif single and path.suffix.lower() in SOURCE_EXTENSIONS and path != source:
                reason = 'single-file import selects only the chosen translation unit'
            elif single and path != source and path.suffix.lower() not in HEADER_EXTENSIONS | RESOURCE_EXTENSIONS:
                reason = 'single-file import copies only the selected source, nearby headers and recognized resource files'
            if reason:
                skipped.append({'path': relative, 'reason': reason})
            else:
                if any(c in relative for c in '$;"\n\r'):
                    raise ValueError('Rename a file containing CMake-special characters before migration: ' + relative)
                total_bytes += path.stat().st_size
                if len(files) >= (1024 if single else 5000) or total_bytes > (64 if single else 256) * 1024 * 1024:
                    raise ValueError('Migration input is too broad (single file: 1024 files/64 MiB; directory: 5000 files/256 MiB). Choose a smaller project directory.')
                files.append((path, relative))
    return base, files, skipped


def create_project(source, output, name='LegacyAddin', dry_run=False):
    source = Path(source).resolve()
    raw_output = Path(output).absolute()
    if _link(raw_output):
        raise ValueError('Output cannot be a symbolic link or junction')
    output = raw_output.resolve()
    if not source.exists() or (source.is_file() and source.suffix.lower() not in SOURCE_EXTENSIONS):
        raise ValueError('Choose an old source directory or a .c/.cpp source file')
    base = source.parent if source.is_file() else source
    if output.exists():
        raise ValueError('Output must be a new directory; existing projects are never overwritten')
    if output.is_relative_to(base) or base.is_relative_to(output):
        raise ValueError('Output must be outside the original project')
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('Project name must contain 1..80 printable characters')
    compat = ROOT / 'compat/fxlib'
    required = ('fxlib.h', 'fxlib.c', 'fxlib_entry.c', 'CMakeLists.txt')
    if not all((compat / file).is_file() for file in required):
        raise ValueError('This SDK package does not contain the complete compat/fxlib module')
    base, files, skipped = _inventory(source)
    units = [relative for _, relative in files if Path(relative).suffix.lower() in SOURCE_EXTENSIONS]
    if not units:
        raise ValueError('No C/C++ translation units remain after excluding old startup/build files')
    headers = [relative for _, relative in files if Path(relative).suffix.lower() in HEADER_EXTENSIONS]
    functions = _catalog(compat)
    warnings, entry_points, main_points = [], [], []
    if source.is_file():
        warnings.append({'kind': 'single-file-scope', 'message': 'Copied the selected source plus nearby headers and recognized resources; other C/C++ units were excluded. Review dependencies and migration-report.json before building.'})
    file_records = []
    for path, relative in files:
        raw = path.read_bytes()
        file_records.append({'path': 'legacy/' + relative, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        if path.suffix.lower() in ('.s', '.src', '.asm'):
            warnings.append({'file': 'legacy/' + relative, 'kind': 'assembly-file',
                             'message': 'Assembly source was preserved but not added to the C/C++ target; review dialect, ABI and startup ownership before adding it.'})
        if path.suffix.lower() in SOURCE_EXTENSIONS | HEADER_EXTENSIONS:
            text, non_utf8 = _source_text(raw)
            if non_utf8:
                warnings.append({'file': 'legacy/' + relative, 'kind': 'encoding', 'message': 'Original bytes preserved; convert non-UTF-8 source before using the IDE editor.'})
            warnings += _scan('legacy/' + relative, text, functions)
            if path.suffix.lower() in SOURCE_EXTENSIONS:
                code = _code_only(text)
                for match in re.finditer(r'\b(AddIn_main|main)\s*\([^;{}]*\)\s*\{', code):
                    (entry_points if match[1] == 'AddIn_main' else main_points).append('legacy/' + relative)
    include_entry = not main_points
    if len(entry_points) != 1 and include_entry:
        warnings.append({'kind': 'entry-point', 'message': f'Expected one AddIn_main definition, found {len(entry_points)}; resolve before building.'})
    if main_points:
        warnings.append({'kind': 'entry-point', 'message': 'Existing main retained; it must call fxlib_compat_init() before fxlib calls. The AddIn_main adapter is not added.'})
    if len(main_points) > 1:
        warnings.append({'kind': 'entry-point', 'message': 'Multiple main definitions require choosing/removing translation units in CMakeLists.txt.'})
    target = re.sub(r'[^A-Za-z0-9_]', '_', name).strip('_') or 'legacy_addin'
    if not target[0].isalpha():
        target = 'legacy_' + target
    target = target[:48]
    if target in ('fxlib_compat', 'all', 'clean', 'help', 'install', 'test'):
        target = 'legacy_' + target
    cpp = any(Path(x).suffix.lower() != '.c' for x in units)
    lines = ['cmake_minimum_required(VERSION 3.15)', f'project({target} {"C CXX" if cpp else "C"})',
             'include(GenerateG1A)', 'find_package(Gint 2.9 REQUIRED)', 'add_subdirectory(compat/fxlib)', f'add_executable({target}']
    lines += [f'  "legacy/{file}"' for file in units]
    if include_entry:
        lines.append('  compat/fxlib/fxlib_entry.c')
    lines += [')', f'target_include_directories({target} PRIVATE']
    include_dirs = sorted({str(Path(x).parent).replace('\\', '/') for x in units + headers})
    lines += ['  "legacy"']
    lines += [f'  "legacy/{folder}"' for folder in include_dirs if folder != '.']
    lines += [')', f'target_compile_options({target} PRIVATE -Wall -Wextra)',
              f'target_link_libraries({target} PRIVATE {"stdc++ " if cpp else ""}Fxlib::Compat)']
    label = re.sub(r'[^A-Za-z0-9 _-]', '_', name).strip('_')[:8] or 'LEGACY'
    lines += [f'generate_g1a(TARGET {target} OUTPUT "{target}.g1a" NAME "{label}" INTERNAL "@LEGACY")', '']
    report = {'schemaVersion': 1, 'project': str(output), 'name': name, 'target': target,
              'sources': ['legacy/' + x for x in units], 'headers': ['legacy/' + x for x in headers],
              'resources': ['legacy/' + relative for _, relative in files if relative not in units + headers],
              'copiedFiles': file_records, 'skipped': skipped, 'warnings': warnings,
              'entryAdapter': include_entry, 'dryRun': dry_run, 'hardwareTested': False,
              'report': str(output / 'migration-report.json'), 'textReport': str(output / 'MIGRATION.txt'),
              'status': 'needs-review' if warnings else 'prepared',
              'limitations': ['Static scanning is advisory, not a complete C compiler/API coverage check.',
                              'Original SHC binary libraries and startup are not linked.',
                              'Check the original char signedness setting; use -fsigned-char explicitly if required by the program.',
                              'Build, emulator and device behavior must be checked after migration.']}
    if dry_run:
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fx-legacy-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'project'
        staging.mkdir()
        for path, relative in files:
            destination = staging / 'legacy' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        shutil.copytree(compat, staging / 'compat/fxlib', ignore=shutil.ignore_patterns('build*', '__pycache__', '*.pyc', '.fxstudio'))
        (staging / 'CMakeLists.txt').write_text('\n'.join(lines), encoding='utf-8')
        (staging / 'fxide.json').write_text(json.dumps({'target': target}, indent=2) + '\n', encoding='utf-8')
        (staging / 'migration-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        text = [name + ' — source migration', '', 'Original source files are copied unchanged under legacy/.',
                'The replacement header/library are under compat/fxlib/. Read its README before assuming API equivalence.',
                'Open CMakeLists.txt in Fx Studio, build, and inspect every diagnostic.',
                'Resource arrays already in C remain C arrays. Use the resource importer for external images.',
                'No old .lib/.a/.obj or Casio startup is linked. No hardware validation is implied.', '', 'Review items:']
        text.insert(-2, 'Review char signedness against the original compiler settings; -fsigned-char is an explicit project choice.')
        text += [f'- {item.get("file", "project")}:{item.get("line", "")} {item["message"]}' for item in warnings] or ['- None found by the limited static scanner.']
        text += ['', 'Excluded files/directories:'] + [f'- {item["path"]}: {item["reason"]}' for item in skipped]
        (staging / 'MIGRATION.txt').write_text('\n'.join(text) + '\n', encoding='utf-8')
        if output.exists():
            raise ValueError('Output appeared during migration; nothing was overwritten')
        staging.rename(output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--source', required=True, type=Path)
    create.add_argument('--output', required=True, type=Path)
    create.add_argument('--name', default='LegacyAddin')
    create.add_argument('--dry-run', action='store_true')
    args = vars(parser.parse_args(argv))
    args.pop('command')
    try:
        print(json.dumps(create_project(**args), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
