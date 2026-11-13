@echo off
rem One-click install for Windows: ffmpeg + tesseract (winget), whisper.cpp + models (lsk setup), skill links for Claude Code / Codex.
rem Same as: lsk.cmd install. Use "install.cmd --skills-only" to only (re)create the skill links.
call "%~dp0lsk.cmd" install %*
set RC=%errorlevel%
if "%~1"=="" pause
exit /b %RC%
