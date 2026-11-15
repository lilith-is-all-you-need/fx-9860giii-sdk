# Core validation — 2026-11-14

## What has passed

The dependency-free test executable verifies MI parsing and command/session behavior. The fixtures do not pretend to simulate a calculator. Current coverage includes nested values/results, repeated fields, MI2 multi-location breakpoint tuples from a real GDB response, octal UTF-8, malformed records, source path mapping, commands completing out of order, asynchronous stops, timeout/cancellation, process failure, and movable project configuration.

`protocol-test.log` records 60 passing checks, including malformed/mismatched ELF/G1A artifacts, exact mismatch offsets, SHA validation, missing executable cleanup, concurrent disposal, pending-command termination and native breakpoint mapping to staged compilation paths.

The `--transport` integration mode executes the actual CAS02 G1A through the native SuperH emulator and Windows GDB. It verifies:

- Register/memory/disassembly reads from the target.
- Register and memory writes, read-back and restoration.
- A GDB variable object.
- Conditional instruction breakpoint at `0x00300202` and precise instruction stepping to `0x00300204`.
- A hardware write watchpoint triggered by the actual CPU's stack write (old 0, new 3735879680).
- Continue, calculator key down/up, asynchronous interrupt and a newly generated screen BMP.
- Graceful GDB detachment.

`integration-work/transport.log` records the actual run. Its ELF argument is deliberately empty, so this mode makes no source-debugging claim.

The `--source-cas01` mode uses the historical CAS01 G1A and the matching audit ELF. The emulator worker independently compared the entire 105288-byte payload and all three nonempty load segments; pairing evidence is `probes/emulator/build/cas01-pairing.json`. Core then verified:

- Source breakpoint at `main`, line 62, local variable types, registers and disassembly.
- Source `next`, `step`, and `finish`.
- Source breakpoint at `ui_draw`, line 766.
- A real two-frame call stack `ui_draw -> main`.
- Typed pointer value `ui->notice` equal to `"Starting CAS"` and structure-field expansion through variable objects.
- Return to `main` and a changed framebuffer from `ui_draw` while still paused. The test deletes any prior BMP and compares frame contents before and after execution.

`integration-work/source-integration.log` records this run. CAS01 is an optimized historical build; GDB reports optimized-out values as such. It is not the new IDE's Debug C/C++ example and does not validate the new offline compiler image.

The generic `ArtifactPairVerifier` independently accepts all 105288 loaded bytes of the paired CAS01 ELF/G1A. It rejects the same ELF with CAS02, reporting the first byte difference at address `0x0030022A` (ELF `0xB9`, G1A `0xB8`), other segment differences and the inconsistent payload extent. Evidence: `integration-work/pair-cas01.json` and `integration-work/pair-cas02-rejected.json`. These local historical binaries are validation inputs, not redistributable test fixtures.

## Running

From the repository root:

```text
dotnet run --project tests/FxStudio.Core.Tests
dotnet run --project tests/FxStudio.Core.Tests -- --transport EMULATOR GDB G1A WORKDIR
dotnet run --project tests/FxStudio.Core.Tests -- --integration EMULATOR GDB ELF G1A WORKDIR
dotnet run --project tests/FxStudio.Core.Tests -- --source-cas01 EMULATOR GDB CAS01_ELF CAS01_G1A WORKDIR
dotnet run --project tests/FxStudio.Core.Tests -- --verify-pair ELF G1A
```

The last mode is specific to the paired historical CAS01 artifact. Do not use it with CAS02 or a different ELF.

## Native path behavior

The installed MinGW GDB rejects an ELF passed with a Chinese absolute directory. Loading its ASCII basename after Windows sets the process working directory to that same Chinese directory was verified successfully. `BuildArtifact.CreateNativeGdbOptions` and the native convenience overload use this strategy. Native ELF filenames themselves should remain ASCII. The primary WSL GDB route keeps Linux paths and avoids this MinGW limitation; it still requires a separate end-to-end run with the new offline toolchain.

## Still required for final IDE acceptance

- Build C and C++ examples using the new image, with verified Debug flags and paired ELF/G1A.
- WSL GDB to Windows emulator on loopback.
- UI startup, editing, build, breakpoint, step, variable edit, screen/key, close and cancellation flows.
- Clean offline import and build from the distributable package.
- Real-calculator installation/run, which needs manual device interaction and has not been performed here.
