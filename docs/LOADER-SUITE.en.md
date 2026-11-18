# Preparing ordinary G1A programs in FxStudio

[中文](LOADER-SUITE.zh-CN.md) · [Oversized Loader source example](../sdk/examples/oversized-loader/README.en.md)

FxStudio accepts a complete ordinary G1A, including the same image renamed to BIN. **The limit is 2,097,152 bytes including the file header.** An image exactly at the limit enters ordinary analysis. A larger file produces an error with its size and the source example location before Ghidra or packaging runs. Authors of larger programs can build the linked example separately.

The limit above governs preparation of existing images. The SDK [build verifier](../tooling/build-project.py) uses a separate conservative deployment budget of 2,000,000 bytes when building a G1A from source. The example builds two small G1As and generates the larger external fixture afterward.

## Prepare and install

Choose Tools → Prepare G1A for Loader. Select the input and output location. The default creates a directory named for each input plus a short SHA. You can include the matching launcher. The WinUI edition also exports launchers independently. Scripts and language models can invoke the same engine from the SDK root.

~~~powershell
python tooling/profile_job.py generate --input game.g1a --output-root results
python tooling/profile_job.py generate --input game.g1a --output-root with-launcher --include-loader --artifacts loader-artifacts
python tooling/profile_job.py export-loader --backend flash --output launchers --artifacts loader-artifacts
~~~

Merge the contents of `calculator` into the calculator storage root. Keep each `FXAPPS/<ID>/` folder intact. Automatic preparation uses `FlashLd.g1a` for ordinary programs, including the original KhiCAS. Select `--backend mapped` explicitly to reproduce the legacy KLoad run for that exact image. Read `requiredLoader` in `analysis.json`. Use Full for the first FlashLd run. Fast trusts earlier content checks and can miss a same-size change between launches.

## Interface reference

| Task | Entry point or result |
| --- | --- |
| Automate preparation | [profile_job.py](../tooling/profile_job.py) provides `generate` and `export-loader`. For generation, exit code 0 means the program folder is ready, 2 means a report needs review, and 1 means processing failed. The CLI emits progress and errors as individual JSON lines. |
| Decide what to test | In `job-result.json`, `programReady` means the program folder is complete and `includesLoader` means it contains a launcher. Device evidence uses its own `hardwareValidated` field. Inspect `diagnostics`, `blockers` and `deepAnalysis.status` for image and Ghidra diagnostics. |
| Save the caller and select a MENU policy | See the [caller-session guide](../sdk/caller-session/README.en.md) and [fx_caller_session.h](../sdk/caller-session/include/fx_caller_session.h). Search for `fxcs_init`, `fxcs_prepare`, `fxcs_handoff`, `fxcs_recover` and `fxcs_error_text`. The caller saves its business state. The general Flash launcher still lacks an arbitrary caller-return backend. |
| Diagnose a device failure | See [FlashLd folders and logs](../probes/storage-loader/FOLDERS.en.md). Preserve the program folder's `RUN.LOG` before another launch and record the final key and screen. Earlier device findings appear in the [pitfalls guide](loader/handbook/PITFALLS.en.txt). |
| Develop an oversized source project | Use the [standalone example's build steps, API map and capacity limits](../sdk/examples/oversized-loader/README.en.md). Its projects explicitly import their vendored runtime. |

Record launch, save, exit and direct MENU re-entry separately during hardware testing. The independent FX Universal Loader project has its own version and scope.

## Memory placement on the calculator

FxProfile includes known RAM reservations in the program folder. FlashLd uses the first suitable OS allocation and retries on overlap. For the original KhiCAS, update both FlashLd.g1a and APP.FPF. Preserve RUN.LOG from the program folder, including RAM_CANDIDATES and REQUIRED_BYTES on failure. [Placement scope, log reference and emulator results](../probes/storage-loader/FOLDERS.en.md)
