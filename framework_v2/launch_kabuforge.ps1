param([string]$PythonPath, [string]$Workspace)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Workspace) { $Workspace = Join-Path $projectRoot 'output/kabuforge_workspace' }
$candidates = @()
if ($PythonPath) { $candidates += $PythonPath }
if ($env:KABUFORGE_PYTHON) { $candidates += $env:KABUFORGE_PYTHON }
$candidates += (Join-Path $projectRoot '.venv-gui/Scripts/python.exe')
$candidates += (Join-Path $projectRoot '.venv/Scripts/python.exe')
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $candidates += $pythonCommand.Source }
$chosenPython = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    & $candidate -B -c 'import PySide6, jsonschema, pandas, requests' 2>$null
    if ($LASTEXITCODE -eq 0) { $chosenPython = $candidate; break }
}
if (-not $chosenPython) {
    throw 'No complete GUI Python environment found. Install framework_v2/requirements-gui.txt into .venv-gui, or pass -PythonPath.'
}
Push-Location $projectRoot
try {
    & $chosenPython -B -m framework_v2.workbench_qt --workspace $Workspace
    if ($LASTEXITCODE -ne 0) { throw "KabuForge exited with code $LASTEXITCODE" }
} finally { Pop-Location }
