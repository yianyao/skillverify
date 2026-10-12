@echo off
rem =============================================================
rem  skillverify console launcher (Windows)
rem
rem  What it does:
rem    1. Detects a usable Python (python / py -3 / python3 / uv).
rem       - If none: offers to install via winget (asks first).
rem       - Handles "Python installed but not on PATH" and
rem         uv-managed Python.
rem    2. Detects how skillverify can run:
rem       - installed entry ("skillverify ..."), or
rem       - repo mode ("python -m skillverify", no install needed).
rem    3. Starts the console bridge (serve_bridge.py, 127.0.0.1
rem       only) in a new window, then opens app\index.html.
rem       The page auto-detects the bridge; without it everything
rem       stays in static mode.
rem
rem  Usage:
rem    start.bat           launch bridge + page (default)
rem    start.bat --check   detection only, starts nothing
rem =============================================================
setlocal EnableExtensions
set "REPO=%~dp0.."
pushd "%REPO%" || (echo Cannot enter repository root: %REPO% & pause & exit /b 1)

echo [1/3] Detecting Python environment ...
set "PY="
call :try_python "python"
if not defined PY call :try_python "py -3"
if not defined PY call :try_python "python3"
if not defined PY call :try_python "uv run python"
if defined PY goto :have_py

echo.
echo   No usable Python found on PATH.
echo   - Python IS installed?  Close and reopen this window ^(PATH refresh^).
echo   - You use uv?           See https://docs.astral.sh/uv/
echo   - Neither?              winget can install Python for you:
set /p "ANS=  Install Python 3.12 now via winget? [y/N] "
if /i not "%ANS%"=="y" goto :fail
where winget >nul 2>nul
if errorlevel 1 (
    echo   winget not available. Install Python from https://www.python.org/downloads/
    goto :fail
)
echo   Installing Python 3.12 via winget ...
winget install --id Python.Python.3.12 -e --source winget
call :try_python "python"
if defined PY goto :have_py
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :have_py
)
echo   Python was installed but is not visible in this window yet.
echo   Close and reopen this window ^(so PATH refreshes^), then run start.bat again.
goto :fail

:have_py
for /f "usebackq delims=" %%v in (`%PY% -c "import sys;print(sys.version.split()[0])"`) do set "PYVER=%%v"
echo   Using Python %PYVER%  [%PY%]

echo [2/3] Detecting how skillverify can run ...
set "BRIDGEARGS="
skillverify --version >nul 2>nul
if not errorlevel 1 (
    echo   Installed entry detected: skillverify
    goto :mode_done
)
echo   No installed entry found - using REPO MODE ^(python -m skillverify, no installation needed^).
set "BRIDGEARGS=--tool-cmd "%PY% -m skillverify""
:mode_done

if /i "%~1"=="--check" (
    echo.
    echo Check-only: detection passed. Nothing was started.
    popd
    exit /b 0
)

echo [3/3] Starting bridge and opening the console page ...
if exist "console\app\index.html" goto :start_bridge
echo   app\index.html not built yet - running console\build.py ...
%PY% console\build.py
if errorlevel 1 goto :fail

:start_bridge
start "skillverify-bridge" cmd /k ""%PY%" console\serve_bridge.py %BRIDGEARGS%"
ping -n 3 127.0.0.1 >nul
start "" "%REPO%\console\app\index.html"
echo.
echo   Bridge window started ^(127.0.0.1:8742 only^). Close that window to stop the bridge.
echo   The page auto-detects the bridge; if it shows static mode, wait a second and refresh.
popd
exit /b 0

:try_python
%~1 -c "import sys" >nul 2>nul && set "PY=%~1"
exit /b 0

:fail
echo.
echo Launch aborted. Fix the issue above and run start.bat again.
popd
pause
exit /b 1
