# Loader Suite: folder packages and dynamic pages

The standalone desktop download includes FxProfile and its matching launchers.
The calculator-only download contains FlashLd, ExtLoad and the KhiCAS-specific KLoad.
Both packages are available from [FX Universal Loader releases](https://github.com/lilith-is-all-you-need/fx_universal_loader/releases).

FX Profile Studio 0.2 is a native WinUI desktop application with English and
Chinese switching. It prepares stable name-plus-short-SHA result directories.
The default output contains program dependencies. Including a launcher is optional;
the separate Export Loader action needs no input image.

Copy the contents of `calculator` to calculator storage, preserving
`FXAPPS/<program-ID>/`. Calculator directory IDs use a name prefix and short hash
within the OS eight-character limit. Keep the shared launcher filename intact.
`IMAGE.BIN` preserves the entire input, including its original offsets and startup.

| Backend | Launcher | Scope |
| --- | --- | --- |
| Ordinary Flash | FlashLd.g1a | Folder discovery, English icon list, profile-bound syscall shadows; ordinary G1As up to 2 MiB, no program whitelist |
| Reviewed original KhiCAS | KLoad.g1a | Exact image and dedicated memory-pool/callback adaptation |
| Source-integrated large runtime | ExtLoad.g1a | ABI-declaring payloads, dynamic resident page table, physical pages queried on the calculator |
| Legacy RAM | Loader.g1a | Historical flat packages only; contiguous heap can be far below the nominal image limit |

Full verification is the default. Fast mode requires a cache written after a
successful full verification; page addresses are still queried each launch and
later address changes within that run are checked. Fast can miss a same-size change between launches. Use Full after
changing a BIN. Each program owns its log and cache; the PC tool never treats a
new zeroed cache as verified.

`EXT.PRF` separates `pageCount = ceil(imageBytes / 4096)` from table capacity.
Spare entries remain invalid and are not mapped to bytes outside the image. The
OS's original 512-entry table is not enlarged. The current 768-entry maximum and
3,000,000-byte package budget are conservative implementation policies, not a claim
that all nominal device storage is available. Profile/image/ABI mismatches, storage
reserve failures and resident allocation failures prevent launch.

## Offline commands

The SDK pins FxProfile and the calculator runtimes to the same upstream commit in
`loader-components.lock.json`. The emulator retains its own revision. To refresh
the Loader snapshot, check out the desired release and run
`python tooling/sync_loader_components.py --universal-loader PATH_TO_CHECKOUT` from
the SDK. Run `python tooling/check_loader_components.py` to verify the offline copy.
Existing projects can still use `sdk/caller-session` and `sdk/fxlarge`.

```powershell
python tooling/profile_job.py generate --input program.g1a --output-root results
python tooling/profile_job.py generate --input program.g1a --output-root with-loader --include-loader --artifacts loader-artifacts
python tooling/profile_job.py export-loader --output launchers --artifacts loader-artifacts
```

`program-ready` means dependencies ready for the shared launcher. `candidate`
includes the launcher. Neither means hardware stability has been established.
`needs-adapter` retains analysis without runnable files; `analysis-incomplete`
means requested Ghidra analysis did not finish. Existing results are reused only
when input, options and delivered file hashes match. Otherwise choose a new root.

## Exception hooks and reusable libraries

The source runtime can route page faults to a permanently resident refill entry
while forwarding other events under an explicit original-handler contract.
Ghidra exports original bytes, exception/VBR ownership sites, delay slots,
functions and recovered targets. `hook-review.json` checks site bytes against the
immutable input. This is evidence, not executable binary patch authorization.
Unknown runtime adapters still need complete VBR-writer coverage, exception-stack
and register ABI, cache/TLB ownership, callbacks, OS transitions and teardown.
EXT v2 rejects unknown nonzero binary-hook records.

`FxStudio::LargeRuntime` is the source integration library. The separate
`sdk/caller-session` library coordinates cooperative business-state transactions
and two MENU policies. It does not yet provide a general Flash backend that
preserves arbitrary caller stacks/heaps or resumes an arbitrary guest. Missing
capabilities and nested A→B→C calls are rejected before pausing or saving A.
SH3-era add-ins require individual MMIO/OS/runtime checks on GIII; a shared
instruction family does not establish compatibility.

Selected older CAS builds first launched on hardware, but direct MENU re-entry
failed. Those records do not validate the new folder/dynamic builds. See
[developer guide](loader/handbook/DEVELOPER-GUIDE.en.txt),
[pitfalls](loader/handbook/PITFALLS.en.txt) and the component validation records.
The emulator remains an HLE model with incomplete cache/peripheral timing and OS
menu lifecycle fidelity.
