@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 wurde nicht gefunden. Installiere Python von python.org und aktiviere "Add Python to PATH".
  pause
  exit /b 1
)

echo [Royal] Abhaengigkeiten werden geprueft ...
py -3 -m pip install -r requirements.lock
if errorlevel 1 (
  echo [Royal] Python-Abhaengigkeiten konnten nicht installiert werden.
  pause
  exit /b 1
)

echo [Royal] Starte die Windows-Anwendung ...
py -3 server.py
if errorlevel 1 pause
