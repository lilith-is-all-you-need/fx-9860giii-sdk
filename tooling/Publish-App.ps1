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
# Publish the console host first. Its NETCore runtime includes facade assemblies
# (notably WindowsBase 4.0) that must not overwrite the desktop runtime's versions.
$agentArguments = @('publish', (Join-Path $root 'src\FxStudio.Agent\FxStudio.Agent.csproj'), '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-o', $stage)
if ($NugetCache) { $agentArguments += "-p:RestorePackagesPath=$NugetCache" }
& $Dotnet @agentArguments
if ($LASTEXITCODE -ne 0) { throw 'Automation agent publish failed.' }
$arguments = @('publish', (Join-Path $root 'src\FxStudio.App\FxStudio.App.csproj'), '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-o', $stage)
if ($NugetCache) { $arguments += "-p:RestorePackagesPath=$NugetCache" }
& $Dotnet @arguments
if ($LASTEXITCODE -ne 0) { throw 'Application publish failed.' }
$desktopVersion = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $stage 'PresentationFramework.dll')).Version
$windowsBaseVersion = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $stage 'WindowsBase.dll')).Version
if ($windowsBaseVersion -ne $desktopVersion) { throw 'The desktop WindowsBase runtime was overwritten by a console runtime.' }
Write-Host "Published self-contained application to $stage"
