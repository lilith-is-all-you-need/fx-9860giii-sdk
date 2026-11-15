Fx Studio 0.2.0 - fx-9860GIII C/C++ development
=============================================

Start with docs/USER-GUIDE.zh-CN.html or docs/USER-GUIDE.en.html.
Research findings: docs/RESEARCH.zh-CN.html
Actual validation and limits: docs/VALIDATION.html

The complete portable release is under dist-windows/FxStudio-0.2.0-win-x64.
Run FxStudio.exe. Build tools, debugger, emulator and .NET runtime are bundled.
No WSL service or online package restoration is required for normal builds.
The calculator receives a .g1a add-in, not the SDK itself.

Development tree:
  src/FxStudio.App              WPF/AvalonEdit desktop UI (Chinese/English)
  src/FxStudio.Core             Build, GDB MI2, emulator and artifact verification
  src/FxStudio.Automation       Versioned domain commands, sessions and snapshots
  src/FxStudio.Agent            Offline MCP stdio server, operations and events
  examples/counter-c{,pp}       Calculator examples
  probes/emulator              Actual SuperH emulator bridge and runtime tests
  tooling                      Native/WSL build services, packaging and validation
  dist-toolchain/native-sdk    Frozen native Windows cross-toolchain
  dist-toolchain/native-gdb    Native GDB and its corresponding-source inventory

App build: tooling/Publish-App.ps1 with a .NET10 SDK and AvalonEdit package.
LLM/script integration: FxStudio.Agent.exe --stdio; docs/AUTOMATION.md.
GNU toolchain build recipes and exact upstream source snapshots are included
in the companion sources archive. Private/proprietary Casio files and ROMs
are not redistributed.

No physical calculator was attached. Full Casio OS emulation, USB, some DSP/
peripheral behavior, C++ exceptions and threads are outside this release.
