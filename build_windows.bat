@echo off
REM Build MuseQuotaWidget on Windows into dist\MuseQuotaWidget\MuseQuotaWidget.exe
REM Usage: double-click this file in Explorer, or run .\build_windows.bat
REM   from PowerShell / cmd in the repo root.
REM
REM Notes (same as build_mac.sh, Windows edition):
REM - Must run on Windows: a build made on Linux/Mac is not a Windows exe.
REM - Use --windowed, NOT --onefile: the QtWebEngine helper process must
REM   stay next to the exe, otherwise the login window cannot find WebEngine.
REM - The output is a folder, not a single exe: dist\MuseQuotaWidget\
REM   contains MuseQuotaWidget.exe plus Qt/WebEngine files. Do not copy
REM   the exe alone to another folder.
REM - The built exe is unsigned: on first run Windows SmartScreen may block
REM   it, click "More info" -> "Run anyway".
REM - Settings, logs and browser cookies stay in %LOCALAPPDATA%\MuseQuotaWidget\,
REM   the same as the python version, so the built exe normally does not
REM   need a fresh login if the python version already logged in on this PC.
REM
REM This file is English-only on purpose: a batch file with Chinese text
REM gets garbled under the default GBK code page on Chinese Windows.

chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found. Install Python 3.10+ first, then run this file again.
  pause
  exit /b 1
)

echo [1/3] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo [ERROR] pip install failed. See the output above.
  pause
  exit /b 1
)

echo [2/3] Building with PyInstaller...
if exist "assets\icon.ico" (
  python -m PyInstaller --clean --noconfirm --windowed --name MuseQuotaWidget --icon "assets\icon.ico" main.py
) else (
  echo [WARNING] assets\icon.ico not found, building without a custom icon.
  echo           Run git pull to get the latest version, then build again.
  python -m PyInstaller --clean --noconfirm --windowed --name MuseQuotaWidget main.py
)
if errorlevel 1 (
  echo [ERROR] PyInstaller build failed. See the output above.
  pause
  exit /b 1
)

echo [3/3] Done.
echo Built: dist\MuseQuotaWidget\MuseQuotaWidget.exe
if exist "dist\MuseQuotaWidget\MuseQuotaWidget.exe" (
  echo Run it with: dist\MuseQuotaWidget\MuseQuotaWidget.exe
) else (
  echo [WARNING] Expected exe not found, check the PyInstaller output above.
)
pause
