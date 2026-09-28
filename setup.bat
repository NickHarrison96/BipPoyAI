@echo off
title Qwythos AI - Setup
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in your PATH.
    echo Please install Python 3.11+ from https://python.org and make sure
    echo "Add python.exe to PATH" is checked during installation.
    pause
    exit /b 1
)

python setup.py %*
if %errorlevel% neq 0 (
    echo.
    echo [!] Setup exited with an error.
    pause
)
