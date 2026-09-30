param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$RunConfig
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this launcher with pwsh.exe (PowerShell 7).' }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $launchArgs = @('-B','-m','framework_v2.workbench_qt','--workspace',$Workspace)
    if ($RunConfig) { $launchArgs += @('--run',$RunConfig) }
    & $PythonPath @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "Workbench exited with code $LASTEXITCODE" }
} finally { Pop-Location }
