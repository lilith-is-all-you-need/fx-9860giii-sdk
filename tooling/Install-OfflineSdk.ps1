[CmdletBinding()]
param(
    [string]$DistroName = 'FxSDK-Dev-20261114',
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'FxSDK-IDE\wsl'),
    [string]$PackageDirectory = (Split-Path $PSScriptRoot -Parent)
)
$ErrorActionPreference = 'Stop'
$manifestPath = Join-Path $PackageDirectory 'toolchain-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Missing toolchain-manifest.json in $PackageDirectory" }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$archive = Join-Path $PackageDirectory $manifest.rootfs.file
if (-not (Test-Path -LiteralPath $archive)) { throw "Missing offline archive: $archive" }
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $manifest.rootfs.sha256) { throw 'Offline archive checksum does not match; installation cancelled.' }
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'Windows Subsystem for Linux is not installed. Install the included prerequisite first and restart Windows if prompted.' }
$names = @(& wsl.exe --list --quiet) -replace "`0", ''
if ($LASTEXITCODE -ne 0) { throw 'Cannot query WSL. Enable the included Windows prerequisite before importing the SDK.' }
if ($names.Trim() -contains $DistroName) { throw "Distribution $DistroName already exists. It has been preserved. Choose another -DistroName to install a second copy." }
$destination = [IO.Path]::GetFullPath($InstallDirectory)
if ((Test-Path -LiteralPath $destination) -and @(Get-ChildItem -Force -LiteralPath $destination).Count) {
    throw "Installation directory is not empty: $destination"
}
New-Item -ItemType Directory -Force -Path $destination | Out-Null
& wsl.exe --import $DistroName $destination $archive --version 1
if ($LASTEXITCODE -ne 0) { throw 'WSL import failed. Existing distributions were not changed.' }
& wsl.exe -d $DistroName --exec /usr/bin/test -x /opt/fxide/bin/build-project
if ($LASTEXITCODE -ne 0) { throw 'The imported SDK did not pass its service check.' }
Write-Host "Offline SDK installed: $DistroName"
Write-Host 'Select this distribution in FX IDE settings. No download is needed for builds.'
