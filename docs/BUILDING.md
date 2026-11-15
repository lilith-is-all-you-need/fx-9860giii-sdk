# Building and maintaining Fx Studio

The portable release is ready for offline calculator development. Rebuilding the desktop application or the compiler itself is a separate developer workflow with additional prerequisites.

## Desktop application and automation host

Use Windows x64, Git, and a .NET 10 SDK. `global.json` accepts stable .NET 10 feature bands. Initial restore needs the AvalonEdit 6.3.1.120 NuGet package and the appropriate .NET runtime packs; cache these first for offline development. The corresponding-source companion contains the AvalonEdit package but does not bundle the .NET SDK.

```powershell
git clone --recurse-submodules https://github.com/lilith-is-all-you-need/fx-9860giii-sdk.git
cd fx-9860giii-sdk
dotnet build FxStudio.slnx -c Release
dotnet run --project tests/FxStudio.Core.Tests -c Release --no-build
dotnet run --project tests/FxStudio.Automation.Tests -c Release --no-build
```

The two test projects are executable test harnesses, not `dotnet test` adapters. These commands run parser/core and automation contract checks without external calculator tools. Native build and emulator integration tests have separate prerequisites and are not implied by a passing contract suite.

To publish the desktop application and MCP host:

```powershell
./tooling/Publish-App.ps1 -StagingDirectory C:\fxstudio-build\publish
```

Publishing these .NET projects alone does not assemble the compiler, GDB, emulator or their corresponding sources. For a local development run, use a separate copy of the complete release as the runtime directory and replace its application files with the published output. Preserve `sdk/`, `runtime/`, `sources/` and license notices. Do not overwrite your only validated release copy.

## Emulator bridge

Initialize the pinned submodule if necessary:

```powershell
git submodule update --init --recursive
./probes/emulator/build-bridge.ps1 -Compiler C:\msys64\mingw64\bin\gcc.exe
```

This build needs Python 3 and MinGW-w64 GCC. It produces `probes/emulator/build/FxEmulator.exe`. `prepare_sources.py` creates patched copies under the ignored build directory; the upstream submodule remains unchanged. See [the bridge documentation](../probes/emulator/README.md) for GDB and control protocols and integration probes.

## Full compiler/SDK and release reconstruction

Download `FxStudio-0.2.0-sources.zip` from the same release. Verify it against `SHA256SUMS.txt`, then extract the dependency material from its `dist-toolchain/` and `licenses/` directories into the same relative locations as this checkout. The companion contains exact GNU/MSYS2 archives, patches, versions and provenance; a GitHub automatic source ZIP does not contain these dependencies or submodule contents.

Read [source-notices/README.md](../source-notices/README.md), [native compiler](../tooling/native-sdk/README.md), [native fxSDK host](../tooling/native-fxsdk/README.md), and the companion's `dist-toolchain/native-gdb/README.md`. These are the recorded build recipes, not a promise of a one-command clean rebuild: native MinGW/MSYS development packages, preserved target runtime inputs, caches and some machine-specific build paths still require setup. The WSL prototype is not needed to use the shipped native release.

`tooling/assemble_package.py` requires real validation records and matching hashes before packaging. Do not replace missing evidence with fabricated pass records. `tooling/collect_public_sources.py` builds the corresponding-source archive; `tooling/Verify-Package.ps1` checks the assembled runtime's inventory.

## Repository and release policy

- Commit original source, examples, documentation, tests and the pinned upstream submodule. Local research, imported third-party games, ROMs, proprietary SDKs, credentials, compiled output and caches stay outside Git.
- Put the full offline runtime and its matching dependency source companion together in a versioned GitHub Release. Keep license notices and checksums with them.
- A GitHub CI pass covers the Windows .NET build and contract tests. It does not certify hardware compatibility, clean toolchain rebuilding or every emulator syscall.
- Before publishing a new version, repeat the native C/C++ build/debug and screen/input integration checks described in [VALIDATION.html](VALIDATION.html).

For slow upstream connections, `tooling/release_transfer.py` can prepare transfer parts for existing validated ZIPs. It replaces stored, hash-pinned public dependency archives with download references and references the source companion once inside the runtime ZIP. The manual `release-transfer.yml` workflow restores the exact original ZIP bytes, verifies full SHA-256 and ZIP CRCs, and uploads them to an existing draft. It does not build new application binaries or publish the draft. Remove temporary `transfer-` assets after verifying the final release attachments.
