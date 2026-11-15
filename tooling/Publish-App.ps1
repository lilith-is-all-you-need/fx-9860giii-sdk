[CmdletBinding()]
param(
    [string]$Dotnet = 'dotnet',
    [string]$NugetCache = '',
    [string]$StagingDirectory = (Join-Path $env:LOCALAPPDATA 'FxStudioBuild\publish')
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = [IO.Path]::GetFullPath($StagingDirectory)
# MSBuild's copy task does not handle apostrophes in PublishDir consistently.
if ($stage.Contains("'")) { throw 'Choose a staging directory without apostrophes.' }
$arguments = @('publish', (Join-Path $root 'src\FxStudio.App\FxStudio.App.csproj'), '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-o', $stage)
if ($NugetCache) { $arguments += "-p:RestorePackagesPath=$NugetCache" }
& $Dotnet @arguments
if ($LASTEXITCODE -ne 0) { throw 'Application publish failed.' }
$agentArguments = @('publish', (Join-Path $root 'src\FxStudio.Agent\FxStudio.Agent.csproj'), '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-o', $stage)
if ($NugetCache) { $agentArguments += "-p:RestorePackagesPath=$NugetCache" }
& $Dotnet @agentArguments
if ($LASTEXITCODE -ne 0) { throw 'Automation agent publish failed.' }
Write-Host "Published self-contained application to $stage"
