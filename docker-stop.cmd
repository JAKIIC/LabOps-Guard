@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker-stop.ps1"
if errorlevel 1 pause
