# Create a local launcher beside the project. No desktop/global settings are changed.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$shellExe = (Get-Command pwsh.exe).Source
$launcher = Join-Path $PSScriptRoot 'launch_kabuforge.ps1'
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut((Join-Path $projectRoot 'KabuForge.lnk'))
$shortcut.TargetPath = $shellExe
$shortcut.Arguments = '-NoLogo -NoProfile -WindowStyle Hidden -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'assets/kabuforge.ico') + ',0'
$shortcut.Description = 'KabuForge - Japanese equity research'
$shortcut.Save()
Write-Output (Join-Path $projectRoot 'KabuForge.lnk')
