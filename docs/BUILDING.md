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

The script publishes the console agent first and the WPF application last so the desktop runtime wins shared-file conflicts. Publishing the agent over the application replaces `WindowsBase.dll` with the NETCore facade and prevents the GUI from starting. Validate the merged output, not only the separate application publish directory.

Run `tooling/Test-PublishedApp.ps1 -ApplicationDirectory C:\fxstudio-build\publish`
to render the actual merged GUI with a fresh profile and check Agent discovery.
Windows CI runs this after publishing, in addition to the assembly-version gate.

The standalone `skills/fxstudio` add-on needs a complete offline runtime but no
client MCP registration. Verify it with `python tooling/test_skill_bridge.py
--package C:\FxStudio --output C:\fxstudio-build\skill-check` (use a fresh output
directory). This exercises separate CLI invocations, concurrent startup, isolated
hosts, request deduplication, a real C++ build/debug/key/screen sequence and Release
output. Package it with `python tooling/package_skill.py --output
C:\fxstudio-build\FxStudio-skill-1.0.0.zip`. It is also included by the full runtime
and corresponding-source assemblers.

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

## Engineering scaffolds and knowledge migration

Read [the engineering handbook](engineering/README.md) for the migrated 63-case
KhiCAS record and the scope of reusable lessons. Maintain templates in
`scaffolds/`; run `python tooling/sync_engineering_skill.py` to refresh the skill's
portable copy. Run its `--check` mode and
`python -m unittest discover -s tests -p test_engineering.py` before packaging.
`python tooling/test_guarded_host.py --cc gcc` additionally checks temporary-memory
and rollback contracts with an existing host C compiler. Real target build/debug
validation remains a separate step. Existing released runtime ZIPs are not updated
by these commands.

## Repository and release policy

### Current source: fxlib, resources and package consistency

See [the migration/resource guide](MIGRATION-AND-RESOURCES.zh-CN.md) for the new
public compatibility subset and IDE commands. The original 0.2.0 ZIP remains a
historical release; updating sources does not update an extracted installation.

```powershell
$env:PYTHONUTF8 = '1'
python tooling/sync_fxlib_compat.py --check
python -m unittest discover -s tests -p test_fxlib_compat.py
python -m unittest discover -s tests -p test_legacy_project.py
python -m unittest discover -s tests -p test_project_assets.py
python -m unittest discover -s tests -p test_package_components.py
python tooling/check_loader_components.py
```

Resource conversion tests need Pillow (already included in the native SDK).
Native legacy builds and emulator/device tests are separate from host contracts.
Do not copy proprietary fxlib headers/libraries or historical game sources into
the public compatibility example.

To rebuild the emulator without changing existing installations or cached builds:

```powershell
python tooling/build_emulator_isolated.py --output C:/fxstudio-build/emulator-new
python tooling/check_emulator_build.py --build-dir C:/fxstudio-build/emulator-new/probes/emulator/build
```

The isolated builder needs MinGW GCC and runs the runtime regression suite by
default. Packaging validates current source hashes, not only the executable's
old manifest. The syscall coverage audit must run against freshly prepared
sources; a stale ignored `build/patched` directory is not evidence that the
checked-in source coverage table is wrong.

`package_components.py` supplies the shared Loader/development inventory. Both
full and Loader-suite assemblers include the version-2 folder engine, two
verified launchers (`FlashLd.g1a` and `KLoad.g1a`), registry, public
component snapshots, public fxlib module, portable example and import tools.
The launcher manifest must declare `schemaVersion: 2` and `bundleFormat: 2`;
legacy `Loader.g1a`/`KhiMap.g1a` sets cannot substitute for these artifacts.
Pass `--emulator-build` for the new build directory and the relevant artifact
argument for a complete, hash-verified Loader set. `assemble_loader_suite.py`
requires the merged output of `Publish-App.ps1`, including Core and Agent, so
updating the GUI cannot silently keep old backend assemblies. Its optional
`--profile-studio` accepts a portable SDK-edition Profile Studio directory (`edition: fxstudio-standard`) and
verifies its own manifest before copying it. Otherwise the IDE uses the bundled
`profile_job.py` folder workflow. Additional files in an artifact directory are
not redistributed by the FxStudio assemblers.

The corresponding-source collector also includes the public component-lock
inventory, including Loader sources and profiles. It excludes private game
images, firmware and generated build trees. Existing validation gates still
require actual current test evidence; do not reuse old UI/automation pass records
after changing their binaries. The latest development checks are recorded in
[VALIDATION-COMPAT-20261118.md](VALIDATION-COMPAT-20261118.md).

### Source and release policy

- Commit original source, examples, documentation, tests and the pinned upstream submodule. Local research, imported third-party games, ROMs, proprietary SDKs, credentials, compiled output and caches stay outside Git.
- Put the full offline runtime and its matching dependency source companion together in a versioned GitHub Release. Keep license notices and checksums with them.
- A GitHub CI pass covers the Windows .NET build and contract tests. It does not certify hardware compatibility, clean toolchain rebuilding or every emulator syscall.
- Before publishing a new version, repeat the native C/C++ build/debug and screen/input integration checks described in [VALIDATION.html](VALIDATION.html).

For slow upstream connections, `tooling/release_transfer.py` can prepare transfer parts for existing validated ZIPs. It replaces stored, hash-pinned public dependency archives with download references and references the source companion once inside the runtime ZIP. The manual `release-transfer.yml` workflow restores the exact original ZIP bytes, verifies full SHA-256 and ZIP CRCs, and uploads them to an existing draft. It does not build new application binaries or publish the draft. Remove temporary `transfer-` assets after verifying the final release attachments.

For a packaging correction, `prepare-delta` reuses unchanged compressed members from hash-pinned baseline ZIPs. The workflow stages corrected archives with a `ready-` prefix, preserving the baselines until the maintainer verifies both new archives and switches the final attachment names.

For the independent oversized source example, build its two projects as described in the [example guide](../sdk/examples/oversized-loader/README.en.md).
