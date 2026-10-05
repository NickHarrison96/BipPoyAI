@echo off
setlocal EnableDelayedExpansion
title BipPoyAI - Dependency Checker
cd /d "%~dp0"

echo.
echo ================================================
echo   BipPoyAI Dependency Checker
echo   Scans for the tools this app needs and
echo   opens download pages for anything missing.
echo ================================================
echo.

set "missing=0"

REM ---------------- Python ----------------
set "found="
where python >nul 2>nul && set "found=1"
if not defined found (
    echo [MISSING] python - Python 3.11+ is required.
    set /a missing+=1
    call :offer "https://www.python.org/downloads/"
) else (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo [OLD]     python - 3.11+ required; the installed version is older.
        set /a missing+=1
    ) else (
        echo [OK]       python
    )
)

REM ---------------- Ollama ----------------
set "found="
where ollama >nul 2>nul && set "found=1"
if not defined found if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "found=1"
if not defined found (
    echo [MISSING] ollama - local model server.
    set /a missing+=1
    call :offer "https://ollama.com/download"
) else (
    echo [OK]       ollama
)

REM ---------------- Node.js / npm (optional, for Claude CLI) ----------------
set "found="
where npm >nul 2>nul && set "found=1"
if not defined found (
    echo [OPTIONAL] npm - Node.js; only needed for the Claude CLI integration.
    call :offer "https://nodejs.org/"
) else (
    echo [OK]       npm
)

echo.
echo ================================================
echo   Python packages
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
    echo [SKIP] python is missing, cannot install packages.
) else (
    echo Installing dependencies from requirements.txt ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [WARN] Some packages failed to install. Try: pip install -r requirements.txt
    ) else (
        echo [OK]   Packages installed.
    )
)

echo.
echo ================================================
echo   Summary
echo ================================================
if "!missing!"=="0" (
    echo [OK]   All required tools are present. Ready to run launch.bat.
) else (
    echo [WARN] !missing! required items missing. Install them, then run launch.bat.
)
echo.
pause
exit /b 0

REM ---------------- helpers ----------------
:offer
    set "answer="
    set /p "answer=         Open the download page now? (y/n) [y]: "
    if /i "!answer!"=="" set "answer=y"
    if /i "!answer!"=="y" start "" "%~1"
    exit /b 0
