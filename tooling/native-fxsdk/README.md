# Native Windows fxSDK host tools

This port supplies the host side of an offline fx-9860GIII SDK. It does not build
GCC or claim to replace the device's operating system. Merge
`dist-toolchain/native-fxsdk/prefix` into the compiler prefix (`sdk/native`).

Layout:

- `bin/fxgxa.exe`, `fxg1a.exe`: native x64 G1A packer, statically linked libpng/zlib.
- `bin/fxconv.exe`, `fxsdk.exe`: Unicode launchers for the bundled Python only.
- `bin/fxconv-main.py`, `fxconv.py`, `fxsdk-main.py`: Python tools.
- `host/python`: CPython 3.13.7 embedded x64, Pillow 11.3.0 Windows wheel.
- `host/cmake`: CMake 3.31.8 Windows x64 ZIP, including its copyright notices.
- `host/ninja`: Ninja 1.13.1 Windows x64.
- `lib/cmake/fxsdk`: fxSDK 2.11 modules; FX9860G and G1A paths are ported.
- `licenses`: fxSDK MIT, libpng, zlib, Ninja licenses. Python's license and Pillow's
  dependency notices remain in their upstream runtime directories.

The compiler prefix additionally needs `bin/sh-elf-*`, their host DLL closure,
`sh3eb-elf/include`, `sh3eb-elf/lib`, `lib/gcc/sh3eb-elf/14.1.0`, and GCC's private
executables. Native binutils copied by `test_fxconv.py` are test fixtures; compiler
packaging owns their final versions and licenses.

Prepare and build:

```powershell
python tooling/native-fxsdk/fetch-host.py
python tooling/native-fxsdk/fetch-sources.py
python tooling/native-fxsdk/fetch-libpng.py
python tooling/native-fxsdk/build.py C:/path/to/fxSDK-2.11-source
python tooling/native-fxsdk/test_host.py
python tooling/native-fxsdk/test_fxconv.py
```

`fetch-host.py` uses fixed archive SHA-256 hashes. Existing archive caches make
the fetch steps offline; deployment never invokes them. `build.py` currently
uses `C:/msys64/mingw64` to rebuild host executables, with static libpng 1.6.59
and zlib 1.3.1. Distributed host executables require only Windows system DLLs;
building them is a separate development operation. Source snapshots, patches,
build commands, checksums and dependency archives are kept under
`dist-toolchain/native-fxsdk`.

The native CMake configure command is:

```text
<prefix>/host/cmake/bin/cmake.exe -S <source> -B <build> -G Ninja
  -DCMAKE_MAKE_PROGRAM=<prefix>/host/ninja/ninja.exe
  -DCMAKE_TOOLCHAIN_FILE=<prefix>/lib/cmake/fxsdk/FX9860G.cmake
```

The toolchain locates its prefix relative to itself. The SDK compiler/binutils
require an ASCII build location; FX Studio stages Unicode user projects in an
ASCII work directory. `fxgxa`, PNG reading/writing, embedded Python, and launcher
paths themselves were tested directly under Chinese and space-containing paths.
The `fxsdk` command implements `path sysroot|include|lib` and `--version` only;
the IDE/CMake build service replaces its POSIX build/install commands.

Changes are recorded in `native-host.patch`: binary-mode file creation, Unicode
file I/O, propagating file/icon failures, icon size checks, closed temporary files
before native binutils access, deterministic binary symbols, CMake-native paths
and argument quoting, replacing `sed` and shell path lookups. The unmodified
source copy is `upstream-fxSDK`; original user projects are not edited.

Validation currently includes ten host checks and six actual SuperH conversion
checks: binary-byte identity, all nine G1A header checks, exact CAS01 ELF/G1A
payload pairing, PNG input/output, error propagation, bundled dependency imports
with only System32 on PATH, binary resources, bopti images, relocation-producing
custom data+assembly, CMake FXCONV language, spaced custom-converter lists, and
explicit failure for an empty binary resource instead of leaving stale output.
The historical CAS01 fixture is only validation data and is not a newly built
application. `build-native.py` and native GCC integration are tracked separately.

Only the fx-9860G G1A route is validated here. Other upstream modules remain in
the snapshot for reference; their CG/CP targets and fxlink USB/TUI are not part
of this port's supported feature set.
