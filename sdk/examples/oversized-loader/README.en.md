# Oversized Loader source example for fx-9860GIII

[中文](README.zh-CN.md) · [FxStudio ordinary Loader guide](../../../docs/LOADER-SUITE.en.md)

This example builds two calculator programs. ExtLoad starts a small guest whose source is included. The guest reads a marker from each page, including the first page beyond 2 MiB, then returns. FxStudio's ordinary G1A preparation accepts at most 2,097,152 bytes including the file header.

## Build and run

1. Copy this example to a writable directory. Open `probes/extended-cas` and `probes/source-guest` as separate projects in the complete FxStudio Windows SDK. Build each in Release. The build record identifies each G1A. The commands below use the default artifact paths.
2. From the example directory, use Python 3 and a fresh output directory.

~~~powershell
$guest = "./probes/source-guest/.fxstudio/build/Release/artifacts/addin.g1a"
$loader = "./probes/extended-cas/.fxstudio/build/Release/artifacts/addin.g1a"
python tests/make_source_guest.py $guest ./out/FXAPPS/DEMO513 --bytes 2097156
Copy-Item $loader ./out/ExtLoad.g1a
~~~

3. Copy the contents of `out` to storage root. The files are `ExtLoad.g1a`, `FXAPPS/DEMO513/IMAGE.BIN` and `FXAPPS/DEMO513/EXT.PRF`. Start ExtLoad from the system menu, select DEMO513 and press EXE. The catalog uses the directory name as its title when APP.MET is absent. An icon is optional.
4. The guest reads the first word on every page and checks the marker on page 513. It has no interactive screen. A successful return closes the session. The launcher can be selected again from the system menu. On failure record Error, Stage and Status if displayed. This exercise covers the supplied guest's reads and exit path.

## Source map

| Question | File and contract |
| --- | --- |
| How does a guest join and leave? | [Guest main.c](probes/source-guest/main.c) calls `fxlarge_bind(api)` before using `FxLargeApi` and `fxlarge_unbind()` on exit. Each returns 1 on success and 0 on failure. |
| Where is the API installed? | [runtime.h](probes/source-guest/vendor/fxlarge/include/fxlarge/runtime.h) defines ABI v1. The guest's [CMakeLists.txt](probes/source-guest/CMakeLists.txt) imports `FxStudio::LargeRuntime` from its own vendor directory. Another project must explicitly include the source. |
| How does the launcher find the image? | [Launcher main.c](probes/extended-cas/src/main.c) reads the directory's `EXT.PRF` and `IMAGE.BIN`, checks size and hash, and queries page addresses on the calculator. |
| Where are page counts and failures defined? | See `encode_profile` and `decode_profile` in [ext_profile.py](tooling/ext_profile.py) and [profile.h](probes/extended-cas/vendor/fxlarge/include/fxlarge/profile.h). `pageCount` rounds file size up to 4096-byte pages. Default `pageCapacity` rounds that count up to a multiple of 16. The fixture uses 513 and 528 respectively. |
| What fits? | This example caps table capacity at 768 pages. The PC preparation budget is 3,000,000 bytes including metadata and the default 8192-byte reserve. The launcher checks actual free storage and RAM on the calculator. |

`make_source_guest.py` fills page markers specifically for the supplied test program. Its code must fit on the first page and the final page must contain at least four bytes. Porting a different program requires control over its source, startup and exit lifecycle. Renaming an existing binary cannot establish the ABI. Validate timers, callbacks, saves and MENU re-entry for each port.

Local verification on 2026-11-19 built both projects in Debug and Release. With the Release binaries, the firmware-assisted emulator observed one refill beyond page 512, a guest return code of 0 and a released allocation. Physical calculator acceptance of this build is pending.
