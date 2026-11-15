---
name: fxstudio
description: Create, build and debug C/C++ add-ins for Casio fx-9860GIII using a local Fx Studio offline SDK. Use for calculator projects, gint resources, simulator keys/screens and GDB debugging. Works through local shell/file tools without configuring an MCP connection; requires Windows and the complete SDK package.
---

# Fx Studio calculator development

Use the user's installed Fx Studio package and ordinary file/shell tools. The
helper starts `FxStudio.Agent.exe` and maintains its MCP connection internally.
No MCP client registration or GUI session is required. The helper and SDK do not
provide access to a physical calculator or attach to the IDE's current session.

## Locate the runtime

Find the complete package containing `FxStudio.Agent.exe`, `sdk/native`,
`runtime`, and `automation/fxstudio_client.py`. Accept an explicit user path or
`FXSTUDIO_PACKAGE`; otherwise the helper searches the working directory and its
parents, the skill's installation ancestors, and their `dist-windows` folders.
Do not rebuild or download a compiler just because the source checkout lacks it.
If detection fails, ask for the installed package location.

Use the package's `sdk/native/host/python/python.exe` to run this skill's
`scripts/fxstudio.py`. A separately installed Python 3.10+ also works. Quote paths
as separate arguments, especially paths containing spaces, Chinese or apostrophes.
Run `doctor` first; inspect its result before using a detected package.

For copyable PowerShell commands, installation and troubleshooting, read
[the Chinese quickstart](references/quickstart.zh-CN.md).

## Keep one host for a task

Choose a unique absolute `--state` directory for this task, such as
`<project>/.fxstudio/skill/<task-name>`. Keep using it for all commands. Different
agents/tasks must use different state directories and, when building concurrently,
separate project copies or build directories. Never stop an unrelated host.

The helper's `start`, `discover`, `call`, `operation`, `events`, `status`, and `stop`
commands share one background Agent until `stop` or the two-hour idle timeout.
`start` prints metadata without credentials. Do not share or commit `bridge.json`.
The loopback helper is an implementation detail; use its CLI, not HTTP directly.

1. `start`, then `discover` to read the current command schemas. Do not guess
   supported commands, arguments or key names. Inspect `discover <command>` for
   the command you need. For key names, see `references/quickstart.zh-CN.md`.
2. Create a new project by copying `examples/counter-c` or `counter-cpp` into the
   requested workspace, omitting `.fxstudio`, `build*` and `project.fxide.json`.
   Edit source/CMake/resources with normal file tools. Add source files to CMake;
   the automation interface does not edit source files for you.
3. Submit `session.open`, then `build.run` with `Debug`. For structured arguments,
   prefer a UTF-8 JSON file and `--args-file` to shell-escaped inline JSON.
4. A `call` returns a submission, not necessarily completion. Poll `operation ID`
   until `operation.status` is `succeeded`, `failed` or `cancelled`. IDs and results
   live in `structuredContent.operation`; `session.open` returns
   `structuredContent.operation.result.sessionId`. Read errors/events on failure.
   Follow-up commands for a session must wait for its current operation to finish.
5. `debug.launch` stops at `main` by default. Set a breakpoint after drawing and
   resume before expecting a populated screen. Read `debug.snapshot`; use
   `--screen <absolute.png>` on the completed operation to export its image and
   inspect it with the agent's available image-viewing tool.
6. To test input, resume, send `debug.key`, then pause before inspecting variables.
   Running snapshots are not consistent paused-state snapshots. Stop debugging
   before editing/rebuilding. Use `Release` for the final `.g1a` and report the
   artifact path returned by the build, plus what was actually tested.
7. Close owned sessions when finished, then `stop` this task's helper. It closes
   stdin to the Agent, which releases its debugger/emulator processes.

Use a new request key for each new action or snapshot. Retry an uncertain
submission with the **same** key and identical arguments; the helper prints its
generated key to stderr before sending. A completed snapshot never refreshes
when polled. `operation ID --cancel` cancels the underlying operation; a terminal
timeout alone does not. Do not replay key presses or memory writes with fresh
keys after an ambiguous transport failure. If the host restarted, its IDs and
deduplication history are gone; inspect/rebuild the session explicitly.

## Boundaries that matter

- The runtime is Windows x64; an environment without local process execution
  cannot acquire that capability by loading this skill.
- Builds execute the project's CMake code. Operate on the project the user has
  authorized. Preserve unrelated files/settings and existing local changes.
- C++ exceptions/threads, complete Casio OS/USB emulation and physical-device
  debugging are not provided. Emulator success is not hardware verification.
- A skill cannot repair a broken runtime by describing it. If the GUI exits with
  `WindowsBase` load errors, use the corrected r1-or-later package; the SDK's
  `Verify-Package.ps1` checks the desktop assembly version.
