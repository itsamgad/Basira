@echo off
setlocal enableextensions

rem ─────────────────────────────────────────────────────────────────
rem setup.bat - first-time Windows setup (Phase C)
rem
rem Run once after copying Basira-Workspace to your machine.
rem Creates both venvs and installs Python + Playwright dependencies.
rem Takes ~5 minutes and ~250 MB of disk for the Chromium browser.
rem
rem Re-running is safe: existing venvs are wiped and rebuilt.
rem ─────────────────────────────────────────────────────────────────

cd /d "%~dp0"
set "WORKSPACE=%CD%"

cls
echo.
echo  +----------------------------------+
echo  ^|   Basira -- First-Time Setup     ^|
echo  +----------------------------------+
echo.

where python >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Python 3 is not installed or not in PATH.
  echo.
  echo Fix:
  echo   1. Install Python 3.10+ from https://www.python.org/downloads/
  echo   2. CHECK the box 'Add Python to PATH' during install
  echo   3. Re-run setup.bat
  echo.
  pause
  exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo Using %PY_VER%
echo.

rem ── 1) Engine venv ─────────────────────────────────────────────
echo [1/4] Creating engine venv...
cd /d "%WORKSPACE%\basira-engine"
if exist ".venv" rmdir /S /Q .venv
python -m venv .venv
if %ERRORLEVEL% NEQ 0 goto :venv_fail

echo [2/4] Installing engine dependencies (numpy, pandas, sklearn, ...)...
".venv\Scripts\pip.exe" install -r requirements.txt
if %ERRORLEVEL% NEQ 0 goto :pip_fail
echo.

rem ── 2) Scraper venv ────────────────────────────────────────────
cd /d "%WORKSPACE%\basira-scraper"
echo [3/4] Creating scraper venv...
if exist ".venv" rmdir /S /Q .venv
python -m venv .venv
if %ERRORLEVEL% NEQ 0 goto :venv_fail

echo [4/4] Installing scraper deps + Playwright Chromium ^(~150 MB^)...
".venv\Scripts\pip.exe" install -r requirements.txt
if %ERRORLEVEL% NEQ 0 goto :pip_fail
".venv\Scripts\playwright.exe" install chromium
if %ERRORLEVEL% NEQ 0 goto :playwright_fail

cd /d "%WORKSPACE%"
echo.
echo  ====================================
echo    [OK] Setup complete.
echo  ====================================
echo.
echo  Double-click Basira.bat to launch.
echo.
pause
exit /b 0

:venv_fail
echo.
echo [ERROR] Failed to create venv in %CD%.
echo Manual fix:
echo   cd %CD%
echo   python -m venv .venv
echo.
pause
exit /b 1

:pip_fail
echo.
echo [ERROR] Failed to install Python dependencies in %CD%.
echo Manual fix:
echo   cd %CD%
echo   .venv\Scripts\pip install -r requirements.txt
echo.
pause
exit /b 1

:playwright_fail
echo.
echo [ERROR] Failed to install Playwright Chromium browser.
echo Manual fix:
echo   cd basira-scraper
echo   .venv\Scripts\playwright install chromium
echo.
pause
exit /b 1
