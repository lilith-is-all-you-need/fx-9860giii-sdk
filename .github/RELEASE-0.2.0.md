Fx Studio 0.2.0 provides a portable Windows C/C++ development environment for the Casio fx-9860GIII, including native compiler tools, a SuperH emulator, GDB debugging and a local MCP automation host.

## 下载 / Downloads

- **FxStudio-0.2.0-win-x64.zip**: complete offline application, native SDK, GDB, emulator, examples, Chinese/English guides, license notices and the matching source companion. Extract the complete archive and run `FxStudio.exe`. Windows 10 x64 1903 or later; validated on Windows 10 22H2. Normal builds and debugging do not require WSL, a separate .NET installation or online package restoration.
- **FxStudio-0.2.0-sources.zip**: matching corresponding-source companion with exact upstream dependency archives, build recipes, local patches and notices. It is also included in the Windows package.
- **FxStudio-0.2.0-sources.manifest.json**: source archive identity and per-file inventory.
- **SHA256SUMS.txt**: SHA-256 checksums for the attached ZIPs and source manifest.

GitHub's automatic “Source code” downloads contain the repository snapshot, not the full offline SDK or the complete dependency source companion. Initialize submodules when cloning the repository.

## Included

- Chinese/English WPF IDE, native C/C++ Debug/Release builds and fxSDK/gint resources.
- Real SuperH G1A execution, calculator display and key input.
- Source breakpoints, conditions, watchpoints, stepping, call stack, variables, registers, memory and disassembly through GDB.
- Screen zoom/capture and source-image previews.
- `FxStudio.Agent.exe --stdio` with four stable MCP entry points, versioned commands, operations, events and snapshots.

## Validation and boundaries

The existing release ZIPs retain their previously validated bytes. Their hashes and ZIP integrity were rechecked for this upload. Repository organization, build documentation and CI were added without replacing the release binaries.

The Windows solution builds successfully; 65 core checks and 129 automation contract/state checks passed locally during publication. The bundled validation report records the broader native compiler, GDB/emulator, C++ and UI checks performed for this release. Additional external G1A smoke tests reached interactive Wolfenstein gameplay (movement, turning and shooting) and Fruit Ninja gameplay (cutting and score increase to 12); the games themselves are not included.

The emulator implements only part of the Casio OS/hardware, and these checks are not physical fx-9860GIII verification. Source debugging needs a matching ELF. Full USB/serial behavior, C++ exceptions/threads, reverse debugging, automatic resource compression and a complete converted-resource preview are outside this version. No proprietary Casio SDK or calculator ROM is distributed.

Original Fx Studio code is MIT licensed; every dependency retains its own license. Consult the included notices and source companion before redistribution.
