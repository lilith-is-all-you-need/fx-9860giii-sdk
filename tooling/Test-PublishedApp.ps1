[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ApplicationDirectory,
    [string]$OutputDirectory = (Join-Path ([IO.Path]::GetTempPath()) ('FxStudio-startup-' + [Guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$app = [IO.Path]::GetFullPath($ApplicationDirectory)
$output = [IO.Path]::GetFullPath($OutputDirectory)
$desktop = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $app 'PresentationFramework.dll')).Version
$windowsBase = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $app 'WindowsBase.dll')).Version
if ($windowsBase -ne $desktop) { throw 'WindowsBase is not the matching desktop runtime assembly.' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
$render = Join-Path $output 'startup.png'
if (Test-Path -LiteralPath $render) { throw 'Choose a fresh output directory; an old render must not count as success.' }
$profile = Join-Path $output 'profile'
$stderr = Join-Path $output 'stderr.log'
$arguments = @('--settings-dir', ('"{0}"' -f $profile), '--render-to', ('"{0}"' -f $render))
$process = Start-Process -FilePath (Join-Path $app 'FxStudio.exe') -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardError $stderr
if (-not $process.WaitForExit(45000)) {
    $process.Kill()
    throw 'Published desktop application did not render and exit within 45 seconds.'
}
$process.WaitForExit()
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $render) -or (Test-Path -LiteralPath ($render + '.error.txt'))) {
    throw ('Published GUI startup failed. Inspect ' + $output)
}
$catalog = & (Join-Path $app 'FxStudio.Agent.exe') --describe --data (Join-Path $output 'agent')
if ($LASTEXITCODE -ne 0) { throw 'Published automation host failed to start.' }
$parsed = $catalog | ConvertFrom-Json
if (-not ($parsed.commands | Where-Object name -eq 'debug.launch')) { throw 'Published automation catalog is incomplete.' }
[pscustomobject]@{ passed=$true; desktopAssemblyVersion=$desktop.ToString(); guiRender=$render; agentDiscovery=$true } | ConvertTo-Json
