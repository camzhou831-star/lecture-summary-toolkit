@echo off
rem Double-click to start the Lecture Workbench on Windows. The first run installs whatever is missing.
rem Keep this window open while you use the workbench; close it to stop.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0workbench\setup.ps1"
if errorlevel 1 pause
