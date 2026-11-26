@echo off
setlocal
set "PYTHONPATH=%~dp0src"
cd /d "%~dp0"
start "" pythonw -m e2s
endlocal
