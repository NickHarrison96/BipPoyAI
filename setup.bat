@echo off
title Cayde 420 - Setup
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in your PATH.
    echo Please install Python 3.11+ from https://python.org and make sure
    echo "Add python.exe to PATH" is checked during installation.
    pause
    exit /b 1
)

echo Checking dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [WARN] Could not install dependencies automatically.
    echo If the app fails to start, run: pip install -r requirements.txt
    echo.
)

python setup.py %*
if %errorlevel% neq 0 (
    echo.
    echo [!] Setup exited with an error.
    pause
)
