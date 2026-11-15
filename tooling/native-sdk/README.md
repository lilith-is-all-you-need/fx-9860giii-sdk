# Native compiler build

This builds Windows-hosted binutils 2.42 and GCC 14.1.0 for the same `sh3eb-elf` target used by the fixed fxSDK snapshot. Executable names remain `sh-elf-*`, and multilib variants remain `m3,m4-nofpu`. It does not rebuild target libc, gint, OpenLibm, libgcc or libstdc++; `copy_target_runtime.py` copies their verified headers/archives/objects and records SHA-256 for every file.

Build workspace: `%USERPROFILE%\.codex-build-envs\native-sdk-20261114`. It must use an ASCII path without spaces or apostrophes. The installed prefix is that directory's `prefix` subdirectory and can be merged with the host tools into `sdk/native`.

Run from the repository root:

```text
python tooling/native-sdk/run_build.py
python tooling/native-sdk/copy_target_runtime.py
python tooling/native-sdk/test_objects.py
python tooling/native-sdk/test_lto.py
python tooling/native-sdk/test_gint.py
python tooling/native-sdk/test_relocation.py
```

The build requires the existing MinGW GCC/G++ and static GMP/MPFR/MPC development libraries under `C:\msys64`, MSYS make and shell, and Git for Windows' `cmp`/`diff`. It reads cached upstream source archives from `dist-toolchain/sources/sdk`; it makes no WSL calls and does not modify MSYS or the source SDK installation. Source/configure/build/install logs are copied alongside these scripts.

GCC's native generator programs cannot interpret `/c/...` paths embedded inside generated input files. The build uses relative source paths in the generated GCC Makefile. This changes host build paths, not compiler target semantics or generated calculator code.

The LTO plugin is built independently as a real Windows DLL **before GCC is configured**, so GCC detects linker plugin support. The existing gint and libc archives contain slim LTO objects; the final link must allow GCC 14.1 LTO even when user source compilation uses `-Og -g3 -fno-lto`. A blanket link-level `-fno-lto` cannot consume these archives. The target runtime's existing soft-float libgcc patch remains part of the reused target libraries.

Native final links also require `-flto-partition=none` for these preserved archives. Their LTO sections use zlib; this native compiler emits zstd. In GCC 14.1's normal WPA-to-LTRANS path, previously compressed function bodies can be copied verbatim while the intermediate header describes the new compiler's compression algorithm. The original counter link consequently failed with `original not compressed with zstd`; the identical link with partitioning disabled succeeded. The single-stage LTO setting consumes the original archives without modifying their bytes. `test_gint.py` checks this with real gint/libc/OpenLibm/libgcc and an isolated Windows PATH.

Binutils currently imports `libwinpthread-1.dll`; distribution must include the matching DLL in `bin` and `sh3eb-elf/bin`, notices and corresponding source. GCC driver/frontends, collect2, LTO tools and the plugin import only Windows system DLLs. `pe-imports.json` records the audit. `object-smoke.json`, `lto-smoke.json`, `gint-smoke.json` and `relocation-*.json` record passing real compiler, target-library and relocated-prefix checks without MSYS or other developer tools on PATH. Full CMake examples and IDE debugging remain separate acceptance checks.
