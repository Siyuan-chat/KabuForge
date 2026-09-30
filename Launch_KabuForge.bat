@echo off
pwsh.exe -NoLogo -NoProfile -Command "& '%~dp0framework_v2\launch_kabuforge.ps1'"
if errorlevel 1 pause
