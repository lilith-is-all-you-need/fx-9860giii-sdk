[CmdletBinding()]
param([string]$PackageDirectory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PackageDirectory).TrimEnd('\')
$manifest = Get-Content -Raw -LiteralPath (Join-Path $root 'package-manifest.json') | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1) { throw 'Unsupported package manifest version.' }
$failures = @()
foreach ($file in $manifest.files) {
    $path = [IO.Path]::GetFullPath((Join-Path $root $file.path))
    if (-not $path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid manifest path.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $failures += "Missing: $($file.path)"; continue }
    if ((Get-Item -LiteralPath $path).Length -ne $file.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $file.sha256) {
        $failures += "Changed: $($file.path)"
    }
}
if ($failures.Count) { $failures | Write-Host; throw "$($failures.Count) package files failed verification." }
$desktopVersion = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $root 'PresentationFramework.dll')).Version
$windowsBaseVersion = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $root 'WindowsBase.dll')).Version
if ($windowsBaseVersion -ne $desktopVersion) { throw 'The package contains the console WindowsBase facade instead of the desktop runtime. Republish the WPF application last.' }
Write-Host "Verified $($manifest.files.Count) files. No network access was used."
