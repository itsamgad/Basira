@echo off
setlocal enableextensions enabledelayedexpansion

rem ─────────────────────────────────────────────────────────────────
rem Basira.bat - double-clickable Windows launcher (Phase C)
rem
rem Mirrors Basira.command on macOS:
rem   1. Verify Python 3 + both venvs + entry-point files + HTML UI
rem   2. Free ports 5050 and 5051 (asks before killing)
rem   3. Start engine (5050) + scraper (5051) in minimized windows
rem   4. Wait up to 30s for /health on both
rem   5. Open the preprocessor UI in the default browser
rem   6. Wait for the user to press any key, then shut down cleanly
rem
rem First-time setup: run setup.bat once to create venvs and install deps.
rem
rem Note: closing this window with the X button does NOT stop the servers.
rem Press a key in this window (or Ctrl+C, then y) so the cleanup runs.
rem ─────────────────────────────────────────────────────────────────

cd /d "%~dp0"
set "WORKSPACE=%CD%"
set "ENGINE_DIR=%WORKSPACE%\basira-engine"
set "SCRAPER_DIR=%WORKSPACE%\basira-scraper"
set "LOGS_DIR=%WORKSPACE%\logs"
set "ENGINE_PORT=5050"
set "SCRAPER_PORT=5051"

cls
echo.
echo  +----------------------------------+
echo  ^|   Basira                         ^|
echo  ^|   Intelligent Data Preprocessor  ^|
echo  ^|   v1.0                           ^|
echo  +----------------------------------+
echo.

rem ── 1) Environment checks ──────────────────────────────────────
echo Checking environment...

where python >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
  call :die "Python 3 is not installed or not in PATH." "Install Python 3.10+ from https://www.python.org/downloads/ - check 'Add Python to PATH' during install."
  exit /b 1
)

if not exist "%ENGINE_DIR%\.venv\Scripts\python.exe" (
  call :die "Engine venv not found at basira-engine\.venv" "Run setup.bat once to create the venvs and install dependencies."
  exit /b 1
)

if not exist "%SCRAPER_DIR%\.venv\Scripts\python.exe" (
  call :die "Scraper venv not found at basira-scraper\.venv" "Run setup.bat once to create the venvs and install dependencies."
  exit /b 1
)

if not exist "%ENGINE_DIR%\basira_app.py" (
  call :die "basira-engine\basira_app.py is missing." "Make sure you're running this launcher from the Basira-Workspace folder."
  exit /b 1
)

if not exist "%SCRAPER_DIR%\basira_scraper.py" (
  call :die "basira-scraper\basira_scraper.py is missing." "Make sure you're running this launcher from the Basira-Workspace folder."
  exit /b 1
)

if not exist "%ENGINE_DIR%\basira_preprocessor.html" (
  call :die "basira-engine\basira_preprocessor.html is missing." "The HTML UI is required - make sure the workspace is intact."
  exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   [OK] Python 3 found ^(%PY_VER%^)
echo   [OK] basira-engine\.venv exists
echo   [OK] basira-scraper\.venv exists
echo   [OK] entry-point files present
echo.

rem ── 2) Port checks ─────────────────────────────────────────────
echo Checking ports...
call :free_port %ENGINE_PORT% engine
if errorlevel 1 exit /b 1
call :free_port %SCRAPER_PORT% scraper
if errorlevel 1 exit /b 1
echo   [OK] ports %ENGINE_PORT% and %SCRAPER_PORT% ready
echo.

rem ── 3) Start servers ───────────────────────────────────────────
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
type NUL > "%LOGS_DIR%\engine.log"
type NUL > "%LOGS_DIR%\scraper.log"

echo Starting servers...
start "BasiraEngineServer" /MIN cmd /c ""%ENGINE_DIR%\.venv\Scripts\python.exe" "%ENGINE_DIR%\basira_app.py" >"%LOGS_DIR%\engine.log" 2>&1"
start "BasiraScraperServer" /MIN cmd /c ""%SCRAPER_DIR%\.venv\Scripts\python.exe" "%SCRAPER_DIR%\basira_scraper.py" >"%LOGS_DIR%\scraper.log" 2>&1"
echo   Engine  -^> logs\engine.log
echo   Scraper -^> logs\scraper.log
echo.

rem ── 4) Wait for /health on both (max 30s) ──────────────────────
<nul set /p="Waiting for both services... "
set /a WAITS=0
:wait_loop
call :health %ENGINE_PORT%
set "E=%ERRORLEVEL%"
call :health %SCRAPER_PORT%
set "S=%ERRORLEVEL%"
if "!E!" == "0" if "!S!" == "0" (
  echo ready
  goto wait_done
)
set /a WAITS+=1
if !WAITS! GEQ 30 (
  echo.
  echo [ERROR] Servers did not become healthy within 30 seconds.
  echo --- last 10 lines of engine.log ---
  powershell -NoProfile -Command "Get-Content '%LOGS_DIR%\engine.log' -Tail 10"
  echo --- last 10 lines of scraper.log ---
  powershell -NoProfile -Command "Get-Content '%LOGS_DIR%\scraper.log' -Tail 10"
  call :stop_servers
  call :die "Servers failed to start." "Inspect the full logs in the logs\ folder."
  exit /b 1
)
<nul set /p="."
timeout /t 1 /nobreak >NUL
goto wait_loop
:wait_done

echo   [OK] Engine  ready on http://localhost:%ENGINE_PORT%
echo   [OK] Scraper ready on http://localhost:%SCRAPER_PORT%
echo.

rem ── 5) Open the UI in the default browser ──────────────────────
set "HTML_PATH=%ENGINE_DIR%\basira_preprocessor.html"
set "HTML_URL=file:///%HTML_PATH:\=/%"
echo Opening Basira UI in your default browser...
start "" "%HTML_URL%"
echo   -^> %HTML_URL%
echo.

rem ── 6) Hold open until user presses a key ──────────────────────
echo Basira is running. Press any key in this window to stop both servers.
echo Live log location: %LOGS_DIR%
echo.
pause >NUL

call :stop_servers
echo Goodbye.
exit /b 0


rem ─────────────────────────────────────────────────────────────────
rem  Helper labels
rem ─────────────────────────────────────────────────────────────────

:die
  echo.
  echo [ERROR] %~1
  if not "%~2" == "" (
    echo.
    echo Fix:
    echo   %~2
  )
  echo.
  echo Press any key to close this window...
  pause >NUL
  exit /b 1

:free_port
  set "PORT=%~1"
  set "LABEL=%~2"
  set "FOUND_PID="
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING 2^>NUL') do set "FOUND_PID=%%a"
  if defined FOUND_PID (
    echo   [!] Port %PORT% already in use by PID !FOUND_PID! ^(needed for the %LABEL%^).
    set /p "REPLY=     Kill PID !FOUND_PID! and continue? [y/N] "
    if /i "!REPLY!" == "y" (
      taskkill /F /PID !FOUND_PID! >NUL 2>&1
      timeout /t 1 /nobreak >NUL
      echo   [OK] freed port %PORT%
    ) else (
      call :die "Port %PORT% still in use - aborting." "Stop the existing process or close the other Basira window, then re-run."
      exit /b 1
    )
  )
  exit /b 0

:health
  set "PORT=%~1"
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:%PORT%/health -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
  exit /b %ERRORLEVEL%

:stop_servers
  echo.
  echo Stopping Basira...
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%ENGINE_PORT% " ^| findstr LISTENING 2^>NUL') do taskkill /F /PID %%a >NUL 2>&1
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%SCRAPER_PORT% " ^| findstr LISTENING 2^>NUL') do taskkill /F /PID %%a >NUL 2>&1
  rem Belt-and-suspenders: also kill the titled launcher windows
  taskkill /F /FI "WINDOWTITLE eq BasiraEngineServer" >NUL 2>&1
  taskkill /F /FI "WINDOWTITLE eq BasiraScraperServer" >NUL 2>&1
  echo   [OK] engine stopped
  echo   [OK] scraper stopped
  exit /b 0
