# Fx Studio public source companion

This companion contains Fx Studio's original source, build/test scripts, the exact public emulator snapshot and debugger modifications, compiler/SDK source archives, native Windows host tools' sources, and redistribution notices. `SOURCE-MANIFEST.json` identifies every archive member by size, SHA-256, and purpose. The GNU/MSYS2 upstream archives remain compressed once; generated build trees and runtime copies are excluded.

Fx Studio App/Core and the original bridge/integration code are MIT licensed, as stated in the root `LICENSE`. Each upstream component retains its own license. This archive does not grant rights beyond those licenses.

| Component | Source and license location |
|---|---|
| emuCasioCalc | Exact commit `63e325708e9eea53eb4769b9c057082614ebd919` under `third_party/emuCasioCalc`; MIT and included asset notices. `probes/emulator/prepare_sources.py` and `debugger-hooks.patch` define the changes. |
| GCC 14.1.0, binutils 2.42, target libgcc/libstdc++ | `dist-toolchain/sources/sdk`, including GCC GPL and runtime exception texts in the archives. Fixed target runtime file inventory is in `tooling/native-sdk/target-runtime-manifest.json`. Native host build configuration is in `tooling/native-sdk`. |
| fxSDK, gint, fxlibc, OpenLibm | Exact source snapshots, revisions, build recipes and local patch recorded in `dist-toolchain/sources/sdk/manifest.json`. Their MIT/BSD and other original notices remain in the archives. |
| Native Windows fxSDK tools | `tooling/native-fxsdk`, `dist-toolchain/native-fxsdk/native-host.patch`, build manifest and exact libpng/zlib source packages. |
| GNU GDB 16.3 | `dist-toolchain/native-gdb/gdb-16.3.tar.xz`, GPL licenses, static dependency source packages, build configuration, and the Windows UTF-8 reopening patch. Its README explains offline rebuilding and runtime requirements. |
| Static MinGW host dependencies | Exact MSYS2 `.src.tar.zst` packages contain upstream sources, PKGBUILD and patches. GDB's dependency manifest covers GMP, MPFR, zlib, iconv, expat, termcap, GCC runtime, CRT/headers and winpthreads. `public-source-inputs/native-sdk-dependencies` adds MPC and zstd for the native compiler. These are independent GPL/LGPL/permissive components, not covered by Fx Studio's MIT license. |
| Python 3.13.7, Pillow 11.3.0, CMake 3.31.8, Ninja 1.13.1 | Exact source archives and official binary provenance are under `dist-toolchain/native-fxsdk`. Python/Pillow/CMake notices are in `licenses/`; Ninja and native fxSDK notices are in `licenses/native-fxsdk`. Pillow's Windows wheel notice preserves every bundled codec/font-library notice. The Pillow source includes its Windows dependency build recipes. FreeType is used under the FreeType License; this software uses the FreeType Project. |
| AvalonEdit 6.3.1.120 | MIT license and the exact resolved NuGet package under `dist-toolchain/public-source-inputs/avalonedit`; upstream source: https://github.com/icsharpcode/AvalonEdit. |
| .NET/Windows Desktop runtime 10.0.15 | Official Microsoft license/third-party notices and SDK provenance under `dist-toolchain/public-source-inputs/dotnet-notices`. Public sources: https://github.com/dotnet/runtime/tree/v10.0.15 and https://github.com/dotnet/wpf/tree/v10.0.15. |

GNU GDB is a separate process reached through GDB/MI. The native GDB binary imports only Windows system DLLs and needs no WSL, MSYS2 installation, or Python runtime. Its Unicode activation manifest requires Windows 10 version 1903 or later. The compiler and native build-host programs are packaged separately from their sources.

The fixed SDK target libraries retain their original optimized/LTO representation. Debug compilation applies `-Og`, debugging information, retained frame pointers and no LTO to user source; final linking invokes the GCC LTO plugin for the precompiled SDK libraries. C++ exceptions/threads are not included in the stable target runtime. The experimental KhiCAS exception/SJLJ modifications are excluded.

The old WSL provisioning scripts are preserved as optional development work, with the incomplete state explicitly recorded in `sdk/PROVISIONING-STATUS.md`. They are not a ready offline rootfs and are not used by the native Windows release.

No official Casio SDK, calculator OS ROM, historical KhiCAS CAS01/CAS02 binary, user WSL filesystem, or unrelated research checkout is included. Host/emulator tests are not proof of physical fx-9860GIII compatibility. Public examples have their source in `examples` and `sdk/examples`.

To regenerate after code changes: from the repository root run `python tooling/collect_public_sources.py --prepare --plan` to prepare/validate public inputs, then run `python tooling/collect_public_sources.py` after all release edits are stable. The latter writes `dist-windows/FxStudio-0.2.0-sources.zip` and an external SHA-256/member manifest. It checks for files changing while archiving and verifies the ZIP CRCs before replacing the final archive.

The GitHub source repository tracks the emulator as a pinned submodule and keeps large dependency archives in the release companion. Use `git clone --recurse-submodules` and read `docs/BUILDING.md`. GitHub's automatic source ZIP is not the complete corresponding-source companion or offline runtime. Packaging revision `v0.2.0-r1` restores the correct .NET Windows Desktop `WindowsBase.dll`, includes the corrected publish/verification scripts, and refreshes source inventories. The Fx Studio application and native toolchain binaries are unchanged.
