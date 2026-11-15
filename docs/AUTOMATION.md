# FxStudio automation contract 1.0

The desktop IDE and automation service use the same build/GDB/emulator Core.
The automation service currently owns **separate sessions**. It does not attach to
the GUI's live session, operate a physical calculator, or require an online LLM.
The Windows package includes `FxStudio.Agent.exe`; no additional runtime install
or Python package restoration is needed.

## Architecture and compatibility

```
MCP client / Python script
        │ MCP JSON-RPC over stdin/stdout
FxStudio.Agent       transport, operation journal, retry deduplication, event cursors
        │ versioned domain commands
FxStudio.Automation sessions, lifecycle, snapshots, parameter validation
        │ typed Core calls
FxStudio.Core       native build, artifact verification, GDB MI, emulator control
        │
Native toolchain + actual SuperH emulator
```

Four MCP tools form the stable outer interface:

| Tool | Purpose |
|---|---|
| `fxstudio_discover` | Command catalog, input JSON schemas, independent command versions, effects and limits. Optional `command` selects one definition. |
| `fxstudio_execute` | Submit `{command, version:1, arguments:{...}, requestKey, waitMs:0}`. Returns an operation. |
| `fxstudio_operation` | Read `{operationId, action:"get", waitMs:1000}` or request `action:"cancel"`. |
| `fxstudio_events` | Read `{after:0, limit:100, sessionId?}`; save `nextCursor`. |

New features add commands or optional fields; they do not require new outer tools.
A command's required fields and established meanings cannot change within its
version. Incompatible domain changes require a new command version, and incompatible
envelope changes require a new contract major. Clients discover capabilities rather
than infer them from product version numbers. Unknown commands, unsupported versions
and misspelled arguments are rejected; unsupported features are not advertised.

This is a versioning policy, not a promise that all future functions can be added
without any version change. The same command service is transport-independent; MCP
does not become the internal debugger architecture. A later DAP adapter or GUI
session bridge can reuse the service without changing these four MCP tools.

## Start and connect

Launch `FxStudio.Agent.exe --stdio` from the package. It locates SDK/GDB/emulator
relative to its executable. `--package DIR` overrides that root, and `--data DIR`
selects the session cache. An ASCII cache path may be necessary on systems without
Windows short filenames. `--describe` prints the command catalog as JSON without
starting a debugger. `--help` describes launcher options.

Example MCP client configuration (adapt its configuration container to your client):

```json
{
  "mcpServers": {
    "fxstudio": {
      "command": "C:\\FxStudio\\FxStudio.Agent.exe",
      "args": ["--stdio"]
    }
  }
}
```

Transport implements the published MCP stdio lifecycle: initialize, then
`notifications/initialized`, followed by `tools/list` and `tools/call`. Supported
MCP versions are `2025-11-25` and `2025-06-18`. Domain contract version is **1.0**,
independent of MCP's version. Stdout contains JSON-RPC messages only; there is no
HTTP listener, account, token or network dependency. Tool results include both
`structuredContent` and JSON text. Framebuffer results additionally include a PNG
image block; the structured screen metadata contains its `imageContentIndex`.

Sources: [MCP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Workflow

1. Discover commands and their parameter schemas.
2. Submit `session.open` with `projectPath` pointing to an fxIDE project JSON,
   CMakeLists.txt or project directory. Read the resulting `sessionId`.
3. Submit `build.run` with the session and `configuration:"Debug"`. Poll the
   operation. Use events for build output and diagnostics.
4. Submit `debug.launch` with `stopAt:"main"`. The verified ELF/G1A pair is copied
   into the session cache and the actual SuperH executable runs to the breakpoint.
5. Read `debug.snapshot`; resume, send calculator keys, pause, then read a new
   snapshot. Other commands expose breakpoints, steps, stack-frame selection,
   variables, registers, memory and disassembly.
6. Submit `session.close` when finished. Closing stdin also cancels outstanding
   operations and releases owned emulator/debugger processes.

`tooling/fxstudio_client.py` is a dependency-free Python example using exactly the
same MCP transport. Run it with `--agent PATH --package DIR --project DIR`; its
optional `--screen FILE.png` exports the stopped main() screen, which can be blank
because drawing has not happened yet. It is a client example, not a second protocol.

## State and retry semantics

- Operations progress through `queued`, `running`, then `succeeded`, `failed` or
  `cancelled`. A tool response containing an operation is not proof of completion.
- `requestKey` deduplicates the exact command/version/arguments for this host's
  lifetime. Retrying returns the original operation. Reusing a key for different
  input returns `REQUEST_KEY_CONFLICT`. It is not durable across host restarts.
- An operation result is immutable after completion. A snapshot describes the
  instant it was captured; polling that completed operation does not refresh it.
  Submit a new snapshot with a new key to refresh.
- At most one domain command runs per session. A concurrent command returns
  `BUSY`; it is not silently queued behind a long build. Different sessions can
  operate independently, subject to Core's build-directory locking.
- Cancellation is cooperative. Completed builds, file writes, memory edits and
  key input are not rolled back. Cancelling an MCP request only cancels that RPC
  wait; use `fxstudio_operation` to cancel the underlying domain operation.
- A stopped snapshot reads state under the session command lock. It records
  revision/consistency and per-section failures. Running snapshots do not pause
  the program implicitly and are explicitly inconsistent. They cannot promise
  variable/memory values from the same CPU instant as a live framebuffer.
- Snapshot expressions and variable-child inspection accept restricted variable
  paths. General expressions go through `debug.evaluate`, marked as a mutation
  because assignments can change the target. Automation sets GDB's
  `may-call-functions off`: target function calls, including implicit overloaded
  C++ operators, are disabled even in evaluate. A syntax whitelist alone would
  not make C++ expressions read-only. Ordinary assignment/arithmetic remain usable.
  Snapshots also include actual emulator `targetStatus` (PC, cycles, reason/error),
  so a CPU/syscall error is available without interpreting a log transcript.
- Events have monotonic cursors and bounded retention. `gap:true` explicitly
  reports lost old events. Cursors belong to this process and chosen filter.
- Limits: 8 sessions, 1024 retained operations plus 8 reserved session-close
  submissions, 2048 retained events, 1 MiB per
  request, 32 simultaneous RPCs and a maximum 1000 ms per polling wait. Discovery
  publishes these limits. Once the operation budget is full, use the reserved
  close submissions or close stdin, then start a new host. Operation/event history
  is not persisted across restarts.

## Deliberate boundaries

Builds execute project CMake code: use trusted projects. The service is local but
does not sandbox arbitrary C/C++ build scripts. It is not a general shell runner.
Only native Windows build/debug sessions are implemented in this API. GUI settings
and breakpoints are not silently shared. A session owns its emulator storage;
cross-session save-state persistence and deterministic whole-machine replay have
not been implemented. Full Casio OS/peripheral simulation, complete syscall
coverage and real-device debugging are not implied by command availability.
