@echo off
setlocal
set "PYTHONPATH=%~dp0src"
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" -m e2s
) else (
    start "" pythonw -m e2s
)
endlocal
