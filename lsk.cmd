@echo off
rem lsk launcher for Windows: lsk doctor ^| run ^<subtitles^> ^| finish ^<summary^> ^| review ^<summary^>  (see the tools folder: lsk.py)
rem No non-ASCII text in this file: cmd.exe reads .cmd files in the console code page, so the tools folder is found by looking for lsk.py.
setlocal
set "LSK="
for /d %%D in ("%~dp0*") do if exist "%%D\lsk.py" set "LSK=%%D\lsk.py"
if not defined LSK (echo Error: lsk.py not found next to %~f0 & exit /b 1)
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (py -3 "%LSK%" %*) else (python "%LSK%" %*)
exit /b %errorlevel%
