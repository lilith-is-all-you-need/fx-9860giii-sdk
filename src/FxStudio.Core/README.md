# FxStudio Core

## Current Windows entry points (0.2.0)

Normal builds use the bundled native Windows SDK, not WSL. For automation use
`FxStudio.Agent.exe --stdio` and the stable contract in
[`docs/AUTOMATION.md`](../../docs/AUTOMATION.md). The Automation library is a
transport-independent session layer over this Core. It does not attach to the
desktop IDE's session.

For direct Core integration, set `Backend = "native"` and
`NativeSdkDirectory = Path.Combine(packageRoot, "sdk", "native")` on ProjectConfig.
Use `BuildService.BuildAsync`, then `NativeDebugImage.CreateAsync` to freeze and
verify the ELF/G1A pair. Launch the bundled emulator and call
`frozen.Artifact.CreateNativeGdbOptions(gdbExe, emulator.GdbPort)`.
The native service contract is documented in [`sdk/BUILD-SERVICE.md`](../../sdk/BUILD-SERVICE.md).

The WSL configuration/examples below describe the **optional historical backend**.
They are not the default Windows workflow or proof of a delivered offline WSL image.

No NuGet dependencies; .NET 10. All callbacks are raised on worker threads. A WPF caller must dispatch UI updates.

## Build

```csharp
var project = new ProjectConfig {
    Name = "Counter",
    SourceDirectory = @"C:\projects\counter",
    BuildDirectory = @"C:\projects\counter-build",
    Distro = "FxSDK-Dev-20261114"
};
var build = new BuildService();
build.Log += line => AppendBuildOutput(line);
BuildArtifact artifact = await build.BuildAsync(project, BuildConfiguration.Debug, cancellationToken);
// BuildDirectory receives Debug/ or Release/; existing sources are not edited by Core.
```

`artifact.ElfPath`/`G1APath` are Windows paths. `LinuxElfPath`/`LinuxG1APath` are paths inside the selected WSL distribution. `SourceMappings` translate debugger source locations for the Windows editor; `LinuxSourceMappings` tell Linux GDB where the original Linux source is.

Build entrypoint contract: `/opt/fxide/bin/build-project SOURCE BUILD Debug|Release`, with both paths absolute Linux paths. `BUILD/artifact.json` must contain schemaVersion=1, elf, g1a, sourceDirectory, buildDirectory, and optionally `sourceMappings:[{from,to}]` and `sha256:{elf,g1a}`. Every path in the manifest is an absolute Linux path. Other fields are ignored. Nonzero exit, absent/stale manifest, missing artifacts, invalid ELF/G1A pairing or incorrect hashes are errors. The Linux wrapper owns locking and removal of the earlier manifest. Cancellation calls `/opt/fxide/bin/cancel-build BUILD` to terminate the verified Linux process group, in addition to ending the Windows launcher.

`ProjectConfig.SaveAsync` writes source/build paths relative to the configuration file, so an entire project folder can move to another machine. `LoadAsync` resolves them to absolute paths before use.

`ArtifactPairVerifier.VerifyAsync(elfPath, g1aPath)` returns precise issues, load segments, hashes and compared byte counts. It validates ELF32 big-endian SuperH, G1A header/size/checksum, segment boundaries and each loaded byte using physical load addresses. The result's `ThrowIfInvalid()` or `VerifyOrThrowAsync` rejects mismatches. `artifact.VerifyAsync(ct)` also checks its remembered hashes; call it again immediately before starting a debug session. This detects stale or modified files; it does not authenticate the producer.

## Debug and preview

```csharp
await artifact.VerifyAsync(cancellationToken);
await using var emulator = new EmulatorSession();
await emulator.StartAsync(emulatorExe, artifact.G1APath, framebufferBmp, cancellationToken);
await using var gdb = new GdbSession();
gdb.Output += AppendDebugOutput;
gdb.Stopped += stop => RefreshOnUiThread(gdb.GetStoppedFrame());
gdb.StateChanged += state => UpdateControlsOnUiThread(state);
await gdb.StartAsync(artifact.CreateWslGdbOptions(project, emulator.GdbPort), cancellationToken);
var bp = await gdb.InsertBreakpointAsync("main", ct: cancellationToken);
await gdb.ContinueAsync(cancellationToken);
// On the Stopped event, read locals, stack, registers, memory and disassembly.
await emulator.SendKeyAsync("EXE", true, cancellationToken);
await emulator.SendKeyAsync("EXE", false, cancellationToken);
```

The Windows GDB convenience overload is `StartAsync(gdbExe, elfPath, port, sourceMappings, ct)`; `artifact.CreateNativeGdbOptions(gdbExe, port)` also configures source mappings. Native launch uses the ELF folder as its Unicode process working directory and loads the basename, avoiding MinGW GDB's inability to open some Chinese absolute paths. Keep native ELF basenames ASCII. General `GdbLaunchOptions` accepts an executable and separate argument list, enabling WSL GDB without a shell. Session commands use MI tokens and asynchronous output; no line is interpreted as a response merely because it arrived next. A malformed MI record fails the session. The API never substitutes invented debugger values.

Typed operations include Continue/Pause/Step/Next/Finish, instruction step/next, insert/delete/enable/conditional breakpoints, read/write/access watchpoints, frame selection, locals, expression evaluation, structured variable objects and children, register read/write, memory read/write, and disassembly. Unsupported remote operations remain explicit GDB errors.

`CommandAsync` returns a parsed `MiRecord` for additional GDB/MI commands. It rejects raw newlines; use `MiValue.Quote` for expressions and paths. Token timeouts and cancellation do not abort unrelated commands. Local expression evaluation is an actual GDB evaluation and may change the debug target when the expression assigns a value or invokes a function.

`EmulatorSession` starts `EXE --gdb-port 0 --control-port 0 --framebuffer BMP G1A`, reads a JSON ready event with gdbPort/controlPort, and connects its control socket to loopback. Commands/replies are one JSON object per line. A timed-out control connection is discarded to prevent a delayed reply from acknowledging another key.

## Validation

Run `dotnet run --project tests/FxStudio.Core.Tests` from the repository root. This is a dependency-free test executable. Its protocol fixture only validates parsing, command correlation and lifecycle behavior; it is not a calculator simulation.

For real binary validation: `FxStudio.Core.Tests --integration EMULATOR GDB ELF G1A WORKDIR`. This launches the real emulator and GDB, breaks at main, then reads variables, stack, registers, memory and disassembly. It fails when the target does not actually stop on the breakpoint.

See `tests/FxStudio.Core.Tests/VALIDATION.md` for protocol/transport checks and
`docs/VALIDATION.html` for current native toolchain/UI acceptance and limitations.
