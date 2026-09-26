@echo off
rem 双击启动课程笔记工作台(Windows)。关闭这个窗口会停止工作台。
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m web %*) || (python -m web %*)
if errorlevel 1 pause
