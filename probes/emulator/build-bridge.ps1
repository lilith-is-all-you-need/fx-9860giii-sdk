param([string]$Compiler = 'C:\msys64\mingw64\bin\gcc.exe')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    python probes/emulator/prepare_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare source hooks' }
    $core = @('cpu.c','mem.c','sh7305.c','audio.c','r61524.c','t6k11.c','emu.c') | ForEach-Object { 'probes/emulator/build/patched/' + $_ }
    $os = Get-ChildItem third_party/emuCasioCalc/src/engine/os -Filter '*.c' | ForEach-Object { 'third_party/emuCasioCalc/src/engine/os/' + $_.Name }
    $util = @('g3a.c','keys.c','png.c') | ForEach-Object { 'third_party/emuCasioCalc/src/utils/' + $_ }
    $flags = @('-std=c11','-O2','-g','-Wall','-Wextra','-Wno-unused-parameter','-static','-municode','-include','probes/emulator/bridge_compat.h')
    foreach ($inc in @('probes/emulator/build/patched','probes/emulator','third_party/emuCasioCalc/src/engine/os','third_party/emuCasioCalc/src/views','third_party/emuCasioCalc/src/utils')) { $flags += '-I'; $flags += $inc }
    $sources = $core + $os + $util + @('probes/emulator/bridge_platform.c', 'probes/emulator/bridge.c')
    Set-Content -LiteralPath probes/emulator/build/bridge-build.log -Value ''
    & $Compiler @flags @sources '-lm' '-lws2_32' '-o' 'probes/emulator/build/FxEmulator.exe' 2>&1 | Tee-Object -FilePath probes/emulator/build/bridge-build.log
    if ($LASTEXITCODE -ne 0) { throw "Bridge build failed: $LASTEXITCODE" }
    $manifest = [ordered]@{
        upstreamCommit = (git -C third_party/emuCasioCalc rev-parse HEAD).Trim()
        compiler = (& $Compiler --version | Select-Object -First 1)
        executable = 'FxEmulator.exe'
        bytes = (Get-Item probes/emulator/build/FxEmulator.exe).Length
        sha256 = (Get-FileHash probes/emulator/build/FxEmulator.exe -Algorithm SHA256).Hash.ToLowerInvariant()
        sourcePatchSha256 = (Get-FileHash probes/emulator/debugger-hooks.patch -Algorithm SHA256).Hash.ToLowerInvariant()
        architecture = 'Windows x64'
    }
    $manifest | ConvertTo-Json | Set-Content -Encoding utf8 probes/emulator/build/BUILD-MANIFEST.json
} finally { Pop-Location }
